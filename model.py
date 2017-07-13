import tensorflow as tf
import numpy as np


class NTMCopyModel():
    def __init__(self, args, seq_length, reuse=False):
        self.x = tf.placeholder(name='x', dtype=tf.float32, shape=[args.batch_size, seq_length, args.vector_dim])
        self.y = self.x
        eof = np.zeros([args.batch_size, args.vector_dim + 1])
        eof[:, args.vector_dim] = np.ones([args.batch_size])
        eof = tf.constant(eof, dtype=tf.float32)
        zero = tf.constant(np.zeros([args.batch_size, args.vector_dim + 1]), dtype=tf.float32)

        if args.model == 'LSTM':
            # single_cell = tf.nn.rnn_cell.BasicLSTMCell(args.rnn_size)
            # cannot use [single_cell] * 3 in tensorflow 1.2
            def rnn_cell(rnn_size):
                return tf.nn.rnn_cell.BasicLSTMCell(rnn_size)
            cell = tf.nn.rnn_cell.MultiRNNCell([rnn_cell(args.rnn_size) for _ in range(args.rnn_num_layers)])
        elif args.model == 'NTM':
            import ntm.ntm_cell as ntm_cell
            cell = ntm_cell.NTMCell(args.rnn_size, args.memory_size, args.memory_vector_dim, 1, 1,
                                    addressing_mode='content_and_location',
                                    reuse=reuse,
                                    output_dim=args.vector_dim)

        state = cell.zero_state(args.batch_size, tf.float32)
        self.state_list = [state]
        for t in range(seq_length):
            output, state = cell(tf.concat([self.x[:, t, :], np.zeros([args.batch_size, 1])], axis=1), state)
            self.state_list.append(state)
        output, state = cell(eof, state)
        self.state_list.append(state)

        self.o = []
        for t in range(seq_length):
            output, state = cell(zero, state)
            self.o.append(output[:, 0:args.vector_dim])
            self.state_list.append(state)
        self.o = tf.sigmoid(tf.transpose(self.o, perm=[1, 0, 2]))

        # self.copy_loss = tf.reduce_mean(tf.reduce_sum(tf.square(self.y - self.o), reduction_indices=[1, 2]))
        eps = 1e-8
        self.copy_loss = -tf.reduce_mean(   # cross entropy function
            self.y * tf.log(self.o + eps) + (1 - self.y) * tf.log(1 - self.o + eps)
        )
        with tf.variable_scope('optimizer', reuse=reuse):
            self.optimizer = tf.train.RMSPropOptimizer(learning_rate=args.learning_rate, momentum=0.9, decay=0.95)
            gvs = self.optimizer.compute_gradients(self.copy_loss)
            capped_gvs = [(tf.clip_by_value(grad, -10., 10.), var) for grad, var in gvs]
            self.train_op = self.optimizer.apply_gradients(capped_gvs)
        self.copy_loss_summary = tf.summary.scalar('copy_loss_%d' % seq_length, self.copy_loss)
        # self.merged_summary = tf.summary.merge(self.copy_loss_summary)


class NTMOneShotLearningModel():
    def __init__(self, args):
        self.x_image = tf.placeholder(dtype=tf.float32,
                                      shape=[args.batch_size, args.seq_length, args.image_width * args.image_height])
        self.x_label = tf.placeholder(dtype=tf.float32,
                                      shape=[args.batch_size, args.seq_length, args.n_classes])
        self.y = tf.placeholder(dtype=tf.float32,
                                shape=[args.batch_size, args.seq_length, args.n_classes])

        if args.model == 'LSTM':
            def rnn_cell(rnn_size):
                return tf.nn.rnn_cell.BasicLSTMCell(rnn_size)
            cell = tf.nn.rnn_cell.MultiRNNCell([rnn_cell(args.rnn_size) for _ in range(args.rnn_num_layers)])
        elif args.model == 'NTM':
            import ntm.ntm_cell as ntm_cell
            cell = ntm_cell.NTMCell(args.rnn_size, args.memory_size, args.memory_vector_dim, 1, 1,
                                    addressing_mode='content',
                                    output_dim=args.n_classes)

        state = cell.zero_state(args.batch_size, tf.float32)
        self.state_list = [state]
        self.o = []
        for t in range(args.seq_length):
            output, state = cell(tf.concat([self.x_image[:, t, :], self.x_label[:, t, :]], axis=1), state)
            if args.model == 'LSTM':
                with tf.variable_scope("o2o", reuse=(t > 0)):
                    o2o_w = tf.get_variable('o2o_w', [output.get_shape()[1], args.n_classes],
                                            initializer=tf.random_normal_initializer(mean=0.0, stddev=0.075))
                    o2o_b = tf.get_variable('o2o_b', [args.n_classes],
                                            initializer=tf.random_normal_initializer(mean=0.0, stddev=0.075))
                    output = tf.nn.xw_plus_b(output, o2o_w, o2o_b)
            output = tf.nn.softmax(output, dim=1)
            self.o.append(output)
            self.state_list.append(state)
        self.o = tf.stack(self.o, axis=1)
        self.state_list.append(state)

        eps = 1e-8
        self.learning_loss = -tf.reduce_mean(  # cross entropy function
            tf.reduce_sum(self.y * tf.log(self.o + eps), axis=[1, 2])
        )
        self.learning_loss_summary = tf.summary.scalar('learning_loss', self.learning_loss)

        with tf.variable_scope('optimizer'):
            self.optimizer = tf.train.RMSPropOptimizer(learning_rate=args.learning_rate, momentum=0.9, decay=0.95)
            gvs = self.optimizer.compute_gradients(self.learning_loss)
            capped_gvs = [(tf.clip_by_value(grad, -10., 10.), var) for grad, var in gvs]
            self.train_op = self.optimizer.apply_gradients(capped_gvs)