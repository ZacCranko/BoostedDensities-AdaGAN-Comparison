# Copyright 2017 Max Planck Society
# Distributed under the BSD-3 Software license,
# (See accompanying file ./LICENSE.txt or copy at
# https://opensource.org/licenses/BSD-3-Clause)
"""Class responsible for vizualizing and evaluating trained models.
"""

import os
import logging
import tensorflow as tf
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from scipy.stats import multivariate_normal as scipy_normal
from sklearn.neighbors.kde import KernelDensity
import utils

class Metrics(object):
    """A base class implementing metrics, used to assess the quality of AdaGAN.
    Here you will find several metrics, including Coverage (refer to the
    adaGAN arxiv paper), entropy, likelihood (for simple 2d problems) and
    the metric proposed in the Unrolled GAN paper. As well as all the useful
    routines to evaluate, aggregate, and output the metrics. Also, the class
    conveniantly contains some visualizing routines.
    """

    def __init__(self):
        self.l2s = None
        self.Qz = None

    def make_plots(self, opts, step, real_points,
                   fake_points, weights=None, prefix='', max_rows=16):
        """Save plots of samples from the current model to the file.
        Args:
            step: integer, identifying the step number (of AdaGAN or anything)
            real_points: (num_points, dim1, dim2, dim3) array of points from
                the training set.
            fake_points: (num_points, dim1, dim2, dim3) array of points,
                generated by the current model
            weights: (num_points,) array of real-valued weights for real_points
        """

        pic_datasets = ['mnist',
                        'mnist3',
                        'guitars',
                        'cifar10']
        if opts['dataset'] == 'gmm':
            if opts['toy_dataset_dim'] == 1:
                self._make_plots_1d(opts, step, real_points,
                                    fake_points, weights, prefix)
            elif opts['toy_dataset_dim'] == 2:
                self._make_plots_2d(opts, step, real_points,
                                    fake_points, weights, prefix)
            else:
                logging.debug('Can not plot, sorry...')
        elif opts['dataset'] == 'circle_gmm':
            if opts['toy_dataset_dim'] == 2:
                self._make_plots_2d(opts, step, real_points,
                                    fake_points, weights, prefix)
            else:
                logging.debug('Can not plot, sorry...')
        elif opts['dataset'] in pic_datasets:
            self._make_plots_pics(opts, step, real_points,
                                  fake_points, weights, prefix, max_rows)
        else:
            logging.debug('Can not plot, sorry...')

    def evaluate(self, opts, step, real_points,
                 fake_points, validation_fake_points=None, prefix=''):
        """Compute various evaluation metrics based on samples.
        Args:
            step: integer, identifying the step number (of AdaGAN or anything)
            real_points: (num_points, dim1, dim2, dim3) array of points from
                the training set.
            fake_points: (num_points, dim1, dim2, dim3) array of points,
                generated by the current model
            validation_fake_points: (num_points, dim1, dim2, dim3) array of
                additional points from the current model.
        """

        if opts['dataset'] == 'gmm':
            return self._evaluate_vec(
                opts, step, real_points,
                fake_points, validation_fake_points, prefix='')
        elif opts['dataset'] == 'circle_gmm':
            return self._evaluate_vec(
                opts, step, real_points,
                fake_points, validation_fake_points, prefix='')
        elif opts['dataset'] == 'mnist':
            return self._evaluate_mnist(
                opts, step, real_points,
                fake_points, validation_fake_points=None, prefix='')
        elif opts['dataset'] == 'mnist3':
            return self._evaluate_mnist3(
                opts, step, real_points,
                fake_points, validation_fake_points=None, prefix='')

        else:
            logging.debug('Can not evaluate, sorry...')
            return None

    def _evaluate_vec(self, opts, step, real_points,
                      fake_points, validation_fake_points, prefix=''):
        """Compute the average log-likelihood and the Coverage metric.
        Coverage metric is defined in arXiv paper. It counts a mass of true
        data covered by the 95% quantile of the model density.
        """

        # Estimating density with KDE
        dist = fake_points[:-1] - fake_points[1:]
        dist = dist * dist
        dist = np.sqrt(np.sum(dist, axis=(1, 2, 3)))
        bandwidth = np.median(dist)
        num_real = len(real_points)
        num_fake = len(fake_points)
        if validation_fake_points is not None:
            max_score = -1000000.
            num_val = len(validation_fake_points)
            b_grid = bandwidth * (2. ** (np.arange(14) - 7.))
            for _bandwidth in b_grid:
                kde = KernelDensity(kernel='gaussian', bandwidth=_bandwidth)
                kde.fit(np.reshape(fake_points, [num_fake, -1]))
                score = np.mean(kde.score_samples(
                    np.reshape(validation_fake_points, [num_val, -1])))
                if score > max_score:
                    # logging.debug("Updating bandwidth to %.4f"
                    #             " with likelyhood %.2f" % (_bandwidth, score))
                    bandwidth = _bandwidth
                    max_score = score
        kde = KernelDensity(kernel='gaussian',
                            bandwidth=bandwidth)
        kde.fit(np.reshape(fake_points, [num_fake, -1]))

        # Computing Coverage, refer to Section 4.3 of arxiv paper
        model_log_density = kde.score_samples(
            np.reshape(fake_points, [num_fake, -1]))
        # np.percentaile(a, 10) returns t s.t. np.mean( a <= t ) = 0.1
        threshold = np.percentile(model_log_density, 5)
        real_points_log_density = kde.score_samples(
            np.reshape(real_points, [num_real, -1]))
        ratio_not_covered = np.mean(real_points_log_density <= threshold)

        log_p = np.mean(real_points_log_density)
        C = 1. - ratio_not_covered

        logging.info('Evaluating: log_p=%.3f, C=%.3f' % (log_p, C))
        return log_p, C

    def _evaluate_mnist(self, opts, step, real_points,
                        fake_points, validation_fake_points, prefix=''):
        assert len(fake_points) > 0, 'No fake digits to evaluate'
        num_fake = len(fake_points)

        # Classifying points with pre-trained model.
        # Pre-trained classifier assumes inputs are in [0, 1.]
        # There may be many points, so we will sess.run
        # in small chunks.

        if opts['input_normalize_sym']:
            # Rescaling data back to [0, 1.]
            if real_points is not None:
                real_points = real_points / 2. + 0.5
            fake_points = fake_points / 2. + 0.5
            if validation_fake_points  is not None:
                validation_fake_points = validation_fake_points / 2. + 0.5

        with tf.Graph().as_default() as g:
            model_file = os.path.join(opts['trained_model_path'],
                                      opts['mnist_trained_model_file'])
            saver = tf.train.import_meta_graph(model_file + '.meta')
            with tf.Session().as_default() as sess:
                saver.restore(sess, model_file)
                input_ph = tf.get_collection('X_')
                assert len(input_ph) > 0, 'Failed to load pre-trained model'
                # Input placeholder
                input_ph = input_ph[0]
                dropout_keep_prob_ph = tf.get_collection('keep_prob')
                assert len(dropout_keep_prob_ph) > 0, 'Failed to load pre-trained model'
                dropout_keep_prob_ph = dropout_keep_prob_ph[0]
                trained_net = tf.get_collection('prediction')
                assert len(trained_net) > 0, 'Failed to load pre-trained model'
                # Predicted digit
                trained_net = trained_net[0]
                logits = tf.get_collection('y_hat')
                assert len(logits) > 0, 'Failed to load pre-trained model'
                # Resulting 10 logits
                logits = logits[0]
                prob_max = tf.reduce_max(tf.nn.softmax(logits),
                                         reduction_indices=[1])

                batch_size = opts['tf_run_batch_size']
                batches_num = int(np.ceil((num_fake + 0.) / batch_size))
                result = []
                result_probs = []
                result_is_confident = []
                thresh = opts['digit_classification_threshold']
                for idx in xrange(batches_num):
                    end_idx = min(num_fake, (idx + 1) * batch_size)
                    batch_fake = fake_points[idx * batch_size:end_idx]
                    _res, prob = sess.run(
                        [trained_net, prob_max],
                        feed_dict={input_ph: batch_fake,
                                   dropout_keep_prob_ph: 1.})
                    result.append(_res)
                    result_probs.append(prob)
                    result_is_confident.append(prob > thresh)
                result = np.hstack(result)
                result_probs = np.hstack(result_probs)
                result_is_confident = np.hstack(result_is_confident)
                assert len(result) == num_fake
                assert len(result_probs) == num_fake

        # Normalizing back
        if opts['input_normalize_sym']:
            # Rescaling data back to [0, 1.]
            if real_points is not None:
                real_points = 2. * (real_points - 0.5)
            fake_points = 2. * (fake_points - 0.5)
            if validation_fake_points  is not None:
                validation_fake_points = 2. * (validation_fake_points - 0.5)

        digits = result.astype(int)
        logging.debug(
            'Ratio of confident predictions: %.4f' %\
            np.mean(result_is_confident))
        # Plot one fake image per detected mode
        gathered = []
        points_to_plot = []
        for (idx, dig) in enumerate(list(digits)):
            if not dig in gathered and result_is_confident[idx]:
                gathered.append(dig)
                p = result_probs[idx]
                points_to_plot.append(fake_points[idx])
                logging.debug('Mode %03d covered with prob %.3f' % (dig, p))
        # Confidence of made predictions
        conf = np.mean(result_probs)
        if len(points_to_plot) > 0:
            self._make_plots_pics(
                opts, step, None, np.array(points_to_plot), None, 'modes_')
        if np.sum(result_is_confident) == 0:
            C_actual = 0.
            C = 0.
            JS = 2.
        else:
            # Compute the actual coverage
            C_actual = len(np.unique(digits[result_is_confident])) / 10.
            # Compute the JS with uniform
            JS = utils.js_div_uniform(digits, 10)
            # Compute Pdata(Pmodel > t) where Pmodel( Pmodel > t ) = 0.95
            # np.percentaile(a, 10) returns t s.t. np.mean( a <= t ) = 0.1
            phat = np.bincount(digits[result_is_confident], minlength=10)
            phat = (phat + 0.) / np.sum(phat)
            logging.debug("Distribution over labels of the current mixture:")
            logging.debug(", ".join(map(str, phat)))
            threshold = np.percentile(phat, 5)
            ratio_not_covered = np.mean(phat <= threshold)
            C = 1. - ratio_not_covered

        logging.info(
            'Evaluating: JS=%.3f, C=%.3f, C_actual=%.3f, Confidence=%.4f' %\
            (JS, C, C_actual, conf))
        return (JS, C, C_actual, conf)

    def _evaluate_mnist3(self, opts, step, real_points,
                         fake_points, validation_fake_points, prefix=''):
        """ The model is covering as many modes and as uniformly as possible.
        Classify every picture in fake_points with a pre-trained MNIST
        classifier and compute the resulting distribution over the modes. It
        should be as close as possible to the uniform. Measure this distance
        with KL divergence. Here modes refer to labels.
        """

        assert len(fake_points) > 0, 'No fake digits to evaluate'
        num_fake = len(fake_points)

        # Classifying points with pre-trained model.
        # Pre-trained classifier assumes inputs are in [0, 1.]
        # There may be many points, so we will sess.run
        # in small chunks.

        if opts['input_normalize_sym']:
            # Rescaling data back to [0, 1.]
            if real_points is not None:
                real_points = real_points / 2. + 0.5
            fake_points = fake_points / 2. + 0.5
            if validation_fake_points  is not None:
                validation_fake_points = validation_fake_points / 2. + 0.5

        with tf.Graph().as_default() as g:
            model_file = os.path.join(opts['trained_model_path'],
                                      opts['mnist_trained_model_file'])
            saver = tf.train.import_meta_graph(model_file + '.meta')
            with tf.Session().as_default() as sess:
                saver.restore(sess, model_file)
                input_ph = tf.get_collection('X_')
                assert len(input_ph) > 0, 'Failed to load pre-trained model'
                # Input placeholder
                input_ph = input_ph[0]
                dropout_keep_prob_ph = tf.get_collection('keep_prob')
                assert len(dropout_keep_prob_ph) > 0, 'Failed to load pre-trained model'
                dropout_keep_prob_ph = dropout_keep_prob_ph[0]
                trained_net = tf.get_collection('prediction')
                assert len(trained_net) > 0, 'Failed to load pre-trained model'
                # Predicted digit
                trained_net = trained_net[0]
                logits = tf.get_collection('y_hat')
                assert len(logits) > 0, 'Failed to load pre-trained model'
                # Resulting 10 logits
                logits = logits[0]
                prob_max = tf.reduce_max(tf.nn.softmax(logits),
                                         reduction_indices=[1])

                batch_size = opts['tf_run_batch_size']
                batches_num = int(np.ceil((num_fake + 0.) / batch_size))
                result = []
                result_probs = []
                result_is_confident = []
                thresh = opts['digit_classification_threshold']
                for idx in xrange(batches_num):
                    end_idx = min(num_fake, (idx + 1) * batch_size)
                    batch_fake = fake_points[idx * batch_size:end_idx]
                    if opts['mnist3_to_channels']:
                        input1, input2, input3 = np.split(batch_fake, 3, axis=3)
                    else:
                        input1, input2, input3 = np.split(batch_fake, 3, axis=2)
                    _res1, prob1 = sess.run(
                        [trained_net, prob_max],
                        feed_dict={input_ph: input1,
                                   dropout_keep_prob_ph: 1.})
                    _res2, prob2 = sess.run(
                        [trained_net, prob_max],
                        feed_dict={input_ph: input2,
                                   dropout_keep_prob_ph: 1.})
                    _res3, prob3 = sess.run(
                        [trained_net, prob_max],
                        feed_dict={input_ph: input3,
                                   dropout_keep_prob_ph: 1.})
                    result.append(100 * _res1 + 10 * _res2 + _res3)
                    result_probs.append(
                        np.column_stack((prob1, prob2, prob3)))
                    result_is_confident.append(
                        (prob1 > thresh) * (prob2 > thresh) * (prob3 > thresh))
                result = np.hstack(result)
                result_probs = np.vstack(result_probs)
                result_is_confident = np.hstack(result_is_confident)
                assert len(result) == num_fake
                assert len(result_probs) == num_fake

        # Normalizing back
        if opts['input_normalize_sym']:
            # Rescaling data back to [0, 1.]
            if real_points is not None:
                real_points = 2. * (real_points - 0.5)
            fake_points = 2. * (fake_points - 0.5)
            if validation_fake_points  is not None:
                validation_fake_points = 2. * (validation_fake_points - 0.5)

        digits = result.astype(int)
        logging.debug(
            'Ratio of confident predictions: %.4f' %\
            np.mean(result_is_confident))
        # Plot one fake image per detected mode
        gathered = []
        points_to_plot = []
        for (idx, dig) in enumerate(list(digits)):
            if not dig in gathered and result_is_confident[idx]:
                gathered.append(dig)
                p = result_probs[idx]
                points_to_plot.append(fake_points[idx])
                logging.debug('Mode %03d covered with prob %.3f, %.3f, %.3f' %\
                              (dig, p[0], p[1], p[2]))
        # Confidence of made predictions
        conf = np.mean(result_probs)
        if len(points_to_plot) > 0:
            self._make_plots_pics(
                opts, step, None, np.array(points_to_plot), None, 'modes_')
        if np.sum(result_is_confident) == 0:
            C_actual = 0.
            C = 0.
            JS = 2.
        else:
            # Compute the actual coverage
            C_actual = len(np.unique(digits[result_is_confident])) / 1000.
            # Compute the JS with uniform
            JS = utils.js_div_uniform(digits)
            # Compute Pdata(Pmodel > t) where Pmodel( Pmodel > t ) = 0.95
            # np.percentaile(a, 10) returns t s.t. np.mean( a <= t ) = 0.1
            phat = np.bincount(digits[result_is_confident], minlength=1000)
            phat = (phat + 0.) / np.sum(phat)
            threshold = np.percentile(phat, 5)
            ratio_not_covered = np.mean(phat <= threshold)
            C = 1. - ratio_not_covered

        logging.info(
            'Evaluating: JS=%.3f, C=%.3f, C_actual=%.3f, Confidence=%.4f' %\
            (JS, C, C_actual, conf))
        return (JS, C, C_actual, conf)

    def _make_plots_2d(self, opts, step, real_points,
                       fake_points, weights=None, prefix=''):

        max_val = opts['gmm_max_val'] * 2
        if real_points is None:
            real = np.zeros([0, 2])
        else:
            num_real_points = len(real_points)
            real = np.reshape(real_points, [num_real_points, 2])
        if fake_points is None:
            fake = np.zeros([0, 2])
        else:
            num_fake_points = len(fake_points)
            fake = np.reshape(fake_points, [num_fake_points, 2])

        # Plotting the sample
        plt.clf()
        plt.axis([-max_val, max_val, -max_val, max_val])
        plt.scatter(real[:, 0], real[:, 1], color='red', s=20, label='real')
        plt.scatter(fake[:, 0], fake[:, 1], color='blue', s=20, label='fake')
        plt.legend(loc='upper left')
        filename = prefix + 'mixture{:02d}.png'.format(step)
        utils.create_dir(opts['work_dir'])
        plt.savefig(utils.o_gfile((opts["work_dir"], filename), 'wb'),
                    format='png')

        # Plotting the weights, if provided
        if weights is not None:
            plt.clf()
            plt.axis([-max_val, max_val, -max_val, max_val])
            assert len(weights) == len(real)
            plt.scatter(real[:, 0], real[:, 1], c=weights, s=40,
                        edgecolors='face')
            plt.colorbar()
            filename = prefix + 'weights{:02d}.png'.format(step)
            utils.create_dir(opts['work_dir'])
            plt.savefig(utils.o_gfile((opts["work_dir"], filename), 'wb'),
                        format='png')

    def _make_plots_1d(self, opts, step, real_points,
                       fake_points, weights=None, prefix=''):

        max_val = opts['gmm_max_val'] * 1.2
        if real_points is None:
            real = np.zeros([0, 2])
        else:
            num_real_points = len(real_points)
            real = np.reshape(real_points, [num_real_points, 1]).flatten()
        if fake_points is None:
            fake = np.zeros([0, 2])
        else:
            num_fake_points = len(fake_points)
            fake = np.reshape(fake_points, [num_fake_points, 1]).flatten()

        # Plotting the sample AND the weights simultaneously
        plt.clf()
        f, _, _ = plt.hist(real, bins=100, range=(-max_val, max_val),
                           normed=True, histtype='step',
                           lw=2, color='red', label='real')
        plt.hist(fake, bins=100, range=(-max_val, max_val), normed=True, histtype='step',
                 lw=2, color='blue', label='fake')
        if weights is not None:
            assert len(real) == len(weights)
            weights_srt = np.array([y for (x, y) in sorted(zip(real, weights))])
            real_points_srt = np.array(sorted(real))
            max_pdf = np.max(f)
            weights_srt = weights_srt / np.max(weights_srt) * max_pdf * 0.8
            plt.plot(real_points_srt, weights_srt, lw=3, color='green', label='weights')
        plt.legend(loc='upper left')
        filename = prefix + 'mixture{:02d}.png'.format(step)
        utils.create_dir(opts['work_dir'])
        plt.savefig(utils.o_gfile((opts["work_dir"], filename), 'wb'),
                    format='png')


    def _make_plots_pics(self, opts, step, real_points,
                         fake_points, weights=None, prefix='', max_rows=16):
        pics = []
        if opts['dataset'] in ('mnist', 'mnist3', 'guitars', 'cifar10'):
            if opts['input_normalize_sym']:
                if real_points is not None:
                    real_points = real_points / 2. + 0.5
                if fake_points is not None:
                    fake_points = fake_points / 2. + 0.5
        num_pics = len(fake_points)
        assert num_pics > 0, 'No points to plot'

        # Loading images
        for idx in xrange(num_pics):
            if opts['dataset'] == 'mnist3':
                if opts['mnist3_to_channels']:
                    # Digits are stacked in channels
                    dig1 = fake_points[idx, :, :, 0]
                    dig2 = fake_points[idx, :, :, 1]
                    dig3 = fake_points[idx, :, :, 2]
                    pics.append(1. - np.concatenate(
                        [dig1, dig2, dig3], axis=1))
                else:
                    # Digits are stacked in width
                    dig1 = fake_points[idx, :, 0:28, :]
                    dig2 = fake_points[idx, :, 28:56, :]
                    dig3 = fake_points[idx, :, 56:84, :]
                    pics.append(1. - np.concatenate(
                        [dig1, dig2, dig3], axis=1))
            else:
                if opts['dataset'] == 'mnist':
                    pics.append(1. - fake_points[idx, :, :, :])
                else:
                    pics.append(fake_points[idx, :, :, :])

        # Figuring out a layout
        num_cols = int(np.ceil(1. * num_pics / max_rows))
        last_col_num = num_pics % max_rows
        if num_cols == 1:
            image = np.concatenate(pics, axis=0)
        else:
            if last_col_num > 0:
                for _ in xrange(max_rows - last_col_num):
                    pics.append(np.ones(pics[0].shape))
            pics = np.array(pics)
            image = np.concatenate(np.split(pics, num_cols), axis=2)
            image = np.concatenate(image, axis=0)

        # Plotting
        dpi = 100
        height_pic = image.shape[0]
        width_pic = image.shape[1]
        height = height_pic / float(dpi)
        width = width_pic / float(dpi)

        if self.l2s is None:
            fig = plt.figure(figsize=(width, height))#, dpi=1)
        elif self.Qz is None:
            fig = plt.figure(figsize=(width, height + height / 2))#, dpi=1)
            gs = matplotlib.gridspec.GridSpec(2, 1, height_ratios=[2, 1])
            plt.subplot(gs[0])
        else:
            fig = plt.figure(figsize=(width, height + height / 2))#, dpi=1)
            gs = matplotlib.gridspec.GridSpec(2, 2, height_ratios=[2, 1])
            plt.subplot(gs[0, :])

        # Showing the image
        if fake_points[0].shape[-1] == 1:
            image = image[:, :, 0]
            ax = plt.imshow(image, cmap='Greys', interpolation='none')
        elif opts['dataset'] == 'mnist3':
            ax = plt.imshow(image, cmap='Greys', interpolation='none')
        else:
            ax = plt.imshow(image, interpolation='none')

        # Removing ticks
        ax.axes.get_xaxis().set_ticks([])
        ax.axes.get_yaxis().set_ticks([])
        ax.axes.set_xlim([0, width_pic])
        ax.axes.set_ylim([height_pic, 0])
        ax.axes.set_aspect(1)

        # Plotting auxiliary stuff
        if self.l2s is not None:
            # Plotting the loss curve
            if self.Qz is None:
                plt.subplot(gs[1])
            else:
                plt.subplot(gs[1,0])
            x = np.arange(1, len(self.l2s) + 1) * opts['plot_every']
            y = np.array(self.l2s)
            delta = 0. if min(y) >= 0. else abs(min(y))
            y = np.log(1e-07 + delta + y)
            plt.plot(x, y)
            if self.Qz is not  None:
                # Plotting the Qz scatter plot
                plt.subplot(gs[1,1])
                # plt.scatter(self.Pz[:,0], self.Pz[:,1], s = 2, color = 'blue')
                plt.scatter(self.Qz[:,0], self.Qz[:,1], s = 20,
                            edgecolors='face', c = self.Qz_labels)
                # plt.scatter(self.Qz[:,0], self.Qz[:,1], s = 10, color='blue')
        # Saving
        filename = prefix + 'mixture{:06d}.png'.format(step)
        utils.create_dir(opts['work_dir'])
        fig.savefig(utils.o_gfile((opts["work_dir"], filename), 'wb'),
                    dpi=dpi, format='png')
        plt.close()

        return True
