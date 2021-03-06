class paramp:
    def __init__(self, vna, pump_src, bias_src):
        self.vna = vna
        self.pump_src = pump_src
        self.bias_src = bias_src
        self.optimal_points = {}
        
        self.target_f = None
        self.target_bw = None
        self.target_power = None
        
        self.hint_fp_offset = 100e6
        self.hint_rel_errors = (1e-4, 1e-2, 1e-2)
        self.hint_maxfun = 200
        self.hint_nop = 5000
        self.hint_span_bw = 30.
        
        self.pump_on = True

    def measure(self):
    # maximize SNR of S21 at given frequency, excitation power and bandwidth
        pna.set_nop(self.hint_nop)
        pna.set_bandwidth(self.target_bw)
        pna.set_power(self.target_power)
        pna.set_centerfreq(self.target_f)
        pna.set_span(self.target_bw/self.hint_span_bw)
    
        params = ((self.pump_src.set_frequency, self.pump_src.get_frequency()),
                  (self.pump_src.set_power, self.pump_src.get_power()),
                  (self.bias_src.set_current, self.bias_src.get_current()))
        initial_simplex=[[p[1]*(1+self.hint_rel_errors[p_id]) if v==p_id else p[1] for p_id,p in enumerate(params)] for v in range(len(params)+1)]
        self.pump_src.set_status(self.pump_on)
        self.bias_src.set_status(True)
    
        def target():
            time.sleep(0.4)
            measurements = pna.measure()['S-parameter'].ravel()
            print (np.log10(np.abs(np.mean(measurements)))*20, np.log10(np.std(measurements)/np.abs(np.mean(measurements)))*10)
            return np.std(measurements)/np.abs(np.mean(measurements))
    
        res = sweep.optimize(target, *params, initial_simplex = initial_simplex, maxfun=self.hint_maxfun)
        for x, p in zip(res[0], params): p[0](x)
        S21 = pna.measure()['S-parameter'].ravel()[0]
        measurement = {'S-parameter':np.asarray(S21), 
                       'SNR':np.asarray(res[1]), 
                       'Pump frequency':np.asarray(res[0][0]), 
                       'Pump power': np.asarray(res[0][1]), 
                       'Bias': np.asarray(res[0][2])}
        return measurement
    
    def set_target_f(self, value):
        self.target_f = value
    
    def set_target_bw(self, value):
        self.target_bw = value
        
    def set_target_power(self, value):
        self.target_power = value
    
    def get_opts(self):
        return {'S-parameter':{'log':20}, 
                'SNR':{'log':20}, 
                'Pump frequency':{'log':False}, 
                'Pump power':{'log':False}, 
                'Bias':{'log':False}}
    
    def get_points(self):
        return {'S-parameter':[],
                'SNR':[], 
                'Pump frequency':[], 
                'Pump power':[], 
                'Bias':[]}
    
    def get_dtype(self):
        return {'S-parameter':np.complex,
                'SNR':np.float, 
                'Pump frequency':np.float, 
                'Pump power':np.float, 
                'Bias':np.float}
                  
    def set_parameters(self, f, power, bias):
        import time
        params = self.measure()
        pump_src.set_frequency(params['Pump frequency'])
        pump_src.set_power(params['Pump power'])
        bias_src.set_current(params['Bias'])
        
    def load_calibration(self, path, name):
        import pickle
        from scipy.interpolate import interp1d
        bias_name = 'Bias Paramp VNA calib'
        pumpfreq_name = 'Pump frequency Paramp VNA calib'
        pumppower_name = 'Pump power Paramp VNA calib'
        self.calib_bias = pickle.load(open('{0}\\{1} {2}.pkl'.format(path, bias_name, name), 'rb'))[1]['Bias'][2]
        self.calib_pumpfreq = pickle.load(open('{0}\\{1} {2}.pkl'.format(path, pumpfreq_name, name), 'rb'))[1]['Pump frequency'][2]
        self.calib_pumppower = pickle.load(open('{0}\\{1} {2}.pkl'.format(path, pumppower_name, name), 'rb'))[1]['Pump power'][2]
        self.calib_targetfreq = pickle.load(open('{0}\\{1} {2}.pkl'.format(path, pumppower_name, name), 'rb'))[1]['Pump power'][1][0]
        self.pump_frequency_by_target_frequency = interp1d(self.calib_targetfreq, self.calib_pumpfreq)
        self.pump_power_by_target_frequency = interp1d(self.calib_targetfreq, self.calib_pumppower)
        self.bias_by_target_frequency = interp1d(self.calib_targetfreq, self.calib_bias)
    
    def load_noise_measurement(self, temp_files, bw):
        import pickle
        self.GN_P = []
        for T, f in temp_files:
            noise_powers = pickle.load(open(f, 'rb'))[1]['Power']
            self.GN_target_frequencies = noise_powers[1][0]
            self.GN_frequencies = noise_powers[1][1]
            self.GN_P.append(10**(noise_powers[2]/10))
        self.G = np.zeros_like(self.GN_P[0])
        self.TN = np.zeros_like(self.GN_P[0])
        for tf_id, tf in enumerate(self.GN_target_frequencies):
            gain, noise_T = self.gain_noise(self.GN_frequencies, np.asarray(self.GN_P)[:, tf_id,:], temp_files[0][0], temp_files[1][0], bw)
            self.G[tf_id, :] = gain
            self.TN[tf_id, :] = noise_T
            #print (noise_powers)
            
    def load_gain_saturation_measurement(self, filename, filter_kernel = (3,3,3)):
        import pickle
        from scipy.signal import medfilt, convolve
        file = open(filename, 'rb')
        data = pickle.load(file)
        data_power = np.abs(data[1]['S-parameter'][2])**2
        filter_kernel = np.ones(filter_kernel)
        data_power_filt = np.transpose(convolve(data_power, filter_kernel/np.sum(filter_kernel), mode='same'), axes=(1,0,2))
        file.close()
        data_filt_diff = np.log10(data_power_filt/data_power_filt[0,:,:])*10
        data_filt_uncompressed = (data_filt_diff>-1)
        pp, tf, pf = np.meshgrid(data[1]['S-parameter'][1][1], 
                                 data[1]['S-parameter'][1][0], 
                                 data[1]['S-parameter'][1][2], 
                                 indexing='ij')
        pp[data_filt_uncompressed]=np.nan
        pp_compression = np.nanmin(pp, axis=0)
        
        compression_1db_1d = np.zeros(data[1]['S-parameter'][1][0].shape, dtype=float)
        for tf_id, _tf in enumerate(data[1]['S-parameter'][1][0]):
            compression_1db_1d[tf_id] = np.interp(_tf, data[1]['S-parameter'][1][2], pp_compression[tf_id,:])
        
        self.sat_1db_ft_freq = pp_compression
        self.sat_1db_ft = compression_1db_1d
        
        self.sat_target_freq = data[1]['S-parameter'][1][0]
        self.sat_freq = data[1]['S-parameter'][1][2]
        
        self.sat_meas = data[1]
        self.sat_meas['1 dB compression point on frequency'] = (('Target frequency', 'Probe frequency'), \
                                                       (self.sat_target_freq, self.sat_freq), self.sat_1db_ft_freq)
        self.sat_meas['1 dB compression point'] = (('Frequency',), (self.sat_target_freq,), self.sat_1db_ft)
        
        return self.sat_meas
    
    def save_gain_saturation_plots(self, name):
        import save_pkl
        calibration_path = get_config().get('datadir')+'/calibrations/paramp/saturation/{0}/'.format(name)
        header = {'name':name, 'type':'gain saturation'}
        save_pkl.save_pkl(header, self.sat_meas, location=calibration_path)
            
    def planck_function(self, f, Ts, gains):
        from scipy.constants import Planck, Boltzmann
        return np.sum([Planck*f*(0.5+1./(np.exp(Planck*f/(Boltzmann*T))-1))*gain for T, gain in zip(Ts, gains)])

    def gain_noise(self, f, P_meas, T1, T2, bw):
        from scipy.constants import Boltzmann
        G_ = np.zeros_like(f)
        TN_ = np.zeros_like(f)
        P_meas = np.asarray(P_meas)*1e-3
        for f_id, f_ in enumerate(f):
            P_in = [self.planck_function(f_, 
                                         [t[0] for t in T1], 
                                         [t[1] for t in T1]), 
                    self.planck_function(f_, 
                                         [t[0] for t in T2], 
                                         [t[1] for t in T2])] # input noise powers
            a = np.asarray([[1, P_in[0]*bw], [1, P_in[1]*bw]])
            b = P_meas[:, f_id].T
            #print (f_id, a.shape, b.shape)
            solution = np.linalg.solve(a, b)
            #print (solution)
            #if (f_id<10):
                #print (a,b, solution)
            GkTNbw, G = solution
            TN = GkTNbw/(Boltzmann*G*bw)
            G_[f_id] = G
            TN_[f_id] = TN
        return G_, TN_
    
    def set_target_freq_calib(self, f):
        self.pump_src.set_frequency(self.pump_frequency_by_target_frequency(f))
        self.pump_src.set_power(self.pump_power_by_target_frequency(f))
        self.bias_src.set_current(self.bias_by_target_frequency(f))
        
    def calibrate_vna(self, frequencies, name):
        calibration_path = get_config().get('datadir')+'/calibrations/paramp/calibration'
        calibration = sweep.sweep(self, 
                                  (freqs, paramp.set_target_f, 'Target frequency'), 
                                  filename='Paramp VNA calibration {0}'.format(name), 
                                  output=False, 
                                  location=calibration_path)
        self.load_calibration(calibration_path, name)