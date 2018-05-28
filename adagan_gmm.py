# Copyright 2017 Max Planck Society
# Distributed under the BSD-3 Software license,
# (See accompanying file ./LICENSE.txt or copy at
# https://opensource.org/licenses/BSD-3-Clause)
"""Training AdaGAN on various datasets.

Refer to the arXiv paper 'AdaGAN: Boosting Generative Models'
Coded by Ilya Tolstikhin, Carl-Johann Simon-Gabriel
"""

import os
import argparse
import logging
import tensorflow as tf
import numpy as np
from datahandler import DataHandler
from adagan import AdaGan
from metrics import Metrics
import utils

flags = tf.app.flags
flags.DEFINE_float("g_learning_rate", 0.01,
                   "Learning rate for Generator optimizers [16e-4]")
flags.DEFINE_float("d_learning_rate", 0.004,
                   "Learning rate for Discriminator optimizers [4e-4]")
flags.DEFINE_float("learning_rate", 0.008,
                   "Learning rate for other optimizers [8e-4]")
flags.DEFINE_float("adam_beta1", 0.5, "Beta1 parameter for Adam optimizer [0.5]")
flags.DEFINE_integer("zdim", 5, "Dimensionality of the latent space [100]")
flags.DEFINE_float("init_std", 0.8, "Initial variance for weights [0.02]")
flags.DEFINE_string("workdir", 'results_gmm', "Working directory ['results']")
flags.DEFINE_bool("unrolled", True, "Use unrolled GAN training [True]")
flags.DEFINE_bool("is_bagging", False, "Do we want to use bagging instead of adagan? [False]")
FLAGS = flags.FLAGS

def main():
    opts = {}
    opts['random_seed'] = 821
    opts['dataset'] = 'gmm' # gmm, circle_gmm,  mnist, mnist3, cifar ...
    opts['unrolled'] = FLAGS.unrolled # Use Unrolled GAN? (only for images)
    opts['unrolling_steps'] = 5 # Used only if unrolled = True
    opts['data_dir'] = 'mnist'
    opts['trained_model_path'] = 'models'
    opts['mnist_trained_model_file'] = 'mnist_trainSteps_19999_yhat' # 'mnist_trainSteps_20000'
    opts['gmm_max_val'] = 15.
    opts['toy_dataset_size'] = 64 * 1000
    opts['toy_dataset_dim'] = 2
    opts['mnist3_dataset_size'] = 2 * 64 # 64 * 2500
    opts['mnist3_to_channels'] = False # Hide 3 digits of MNIST to channels
    opts['input_normalize_sym'] = False # Normalize data to [-1, 1], applicable only for image datasets
    opts['adagan_steps_total'] = 10
    opts['samples_per_component'] = 5000 # 50000
    opts['work_dir'] = FLAGS.workdir
    opts['is_bagging'] = FLAGS.is_bagging
    opts['beta_heur'] = 'uniform' # uniform, constant
    opts['weights_heur'] = 'theory_star' # theory_star, theory_dagger, topk
    opts['beta_constant'] = 0.5
    opts['topk_constant'] = 0.5
    opts["init_std"] = FLAGS.init_std
    opts["init_bias"] = 0.0
    opts['latent_space_distr'] = 'normal' # uniform, normal
    opts['optimizer'] = 'sgd' # sgd, adam
    opts["batch_size"] = 64
    opts["d_steps"] = 1
    opts["g_steps"] = 1
    opts["verbose"] = True
    opts['tf_run_batch_size'] = 100
    opts['objective'] = 'JS'

    opts['gmm_modes_num'] = 3
    opts['latent_space_dim'] = FLAGS.zdim
    opts["gan_epoch_num"] = 15
    opts["mixture_c_epoch_num"] = 5
    opts['opt_learning_rate'] = FLAGS.learning_rate
    opts['opt_d_learning_rate'] = FLAGS.d_learning_rate
    opts['opt_g_learning_rate'] = FLAGS.g_learning_rate
    opts["opt_beta1"] = FLAGS.adam_beta1
    opts['batch_norm_eps'] = 1e-05
    opts['batch_norm_decay'] = 0.9
    opts['d_num_filters'] = 16
    opts['g_num_filters'] = 16
    opts['conv_filters_dim'] = 4
    opts["early_stop"] = -1 # set -1 to run normally
    opts["plot_every"] = 500 # set -1 to run normally
    opts["eval_points_num"] = 1000 # 25600
    opts['digit_classification_threshold'] = 0.999
    opts['inverse_metric'] = False # Use metric from the Unrolled GAN paper?
    opts['inverse_num'] = 1 # Number of real points to inverse.
    
    saver = utils.ArraySaver('disk', workdir=opts['work_dir'])

    if opts['verbose']:
        logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(message)s')
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')

    opts["number_of_runs"] = 15
    likelihood = np.empty((opts["adagan_steps_total"], opts["number_of_runs"]))
    coverage   = np.empty((opts["adagan_steps_total"], opts["number_of_runs"]))

    for run in range(opts["number_of_runs"]):
        logging.info('Beginning run {} of {}'.format(run+1, opts["number_of_runs"]))
        opts['random_seed'] += 1

        utils.create_dir(opts['work_dir'])
        with utils.o_gfile((opts['work_dir'], 'params.txt'), 'w') as text:
            text.write('Parameters:\n')
            for key in opts:
                text.write('%s : %s\n' % (key, opts[key]))

        data = DataHandler(opts)
        # saver.save('real_data_{0:02d}.npy'.format(run), data.data)
        saver.save('real_data_params_mean_{0:02d}_var_{1:1.2f}.npy'.format(run, data.var), data.mean)
        # assert data.num_points >= opts['batch_size'], 'Training set too small'
        # adagan = AdaGan(opts, data)
        # metrics = Metrics()

            
    

        for step in range(opts["adagan_steps_total"]):
            logging.info('Running step {} of AdaGAN'.format(step + 1))
            adagan.make_step(opts, data)
            num_fake = opts['eval_points_num']
            logging.debug('Sampling fake points')
            
            fake_points = adagan.sample_mixture(num_fake)
            saver.save('fake_points_{:02d}.npy'.format(step), fake_points)

            logging.debug('Sampling more fake points')
            more_fake_points = adagan.sample_mixture(500)
            logging.debug('Plotting results')
            metrics.make_plots(opts, step, data.data[:500],
                    fake_points[0:100], adagan._data_weights[:500])
            logging.debug('Evaluating results')
            (lh, C) = metrics.evaluate(
                opts, step, data.data,
                fake_points, more_fake_points, prefix='')
            likelihood[step, run] = lh
            coverage[step, run]   = C
            saver.save('likelihood.npy', likelihood)
            saver.save('coverage.npy',   coverage)
        logging.debug("AdaGan finished working!")

if __name__ == '__main__':
    main()
