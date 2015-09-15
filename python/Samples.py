#!/usr/bin/env python
__doc__ = """

Dataset Class Interface (CSamples)

Jingpeng Wu <jingpeng.wu@gmail.com>,
Nicholas Turner <nturner@cs.princeton.edu>, 2015
"""

import sys

import numpy as np
from numba import autojit

import emirt

class CImage(object):
    """
    A class which represents a stack of images (up to 4 dimensions)

    In the 4-dimensional case, it can constrain the constituent 3d volumes
    to be the same size.

    The design of the class is focused around returning subvolumes of a
    particular size (setsz). It can accomplish this by specifying a deviation
    (in voxels) from the center. The class also internally performs
    rotations and flips for data augmentation.
    """

    def __init__(self, config, pars, sec_name, setsz):

        #Parameter object (see parser above)
        self.pars = pars
        #Desired size of subvolumes returned by this instance
        self.setsz = setsz

        #Reading in data
        fnames = config.get(sec_name, 'fnames').split(',\n')
        arrlist = self._read_files( fnames );
        
        #Auto crop - constraining 3d vols to be the same size
        self._is_auto_crop = config.getboolean(sec_name, 'is_auto_crop')
        if self._is_auto_crop:
            arrlist = self._auto_crop( arrlist )

        #4d array of all data
        self.arr = np.asarray( arrlist, dtype='float32')
        #3d shape of a constituent volume
        self.sz = np.asarray( self.arr.shape[1:4] )
        
        #Computes center coordinate, picks lower-index priority center
        self.center = self._get_center()

        #Number of voxels with index lower than the center
        # within a subvolume (used within get_dev_range, and
        # get_sub_volume)
        self.low_setsz  = (self.setsz-1)/2
        #Number of voxels with index higher than the center
        # within a subvolume (used within get_dev_range, and
        # get_sub_volume)
        self.high_setsz = self.setsz / 2

        #Display some instance information
        print "image stack size:    ", self.arr.shape
        print "set size:            ", self.setsz
        print "center:              ", self.center
        return

    def get_dev_range(self):
        """
        Subvolumes are specified in terms of 'deviation' from the center voxel

        This function specifies the valid range of those deviations in terms of
        xyz coordinates
        """

        #Number of voxels within index lower than the center
        low_sz  = (self.sz - 1) /2
        #Number of voxels within index higher than the center
        high_sz = self.sz/2

        low  = -( low_sz - self.low_setsz )
        high = high_sz - self.high_setsz

        print "deviation range:     ", low, "--", high

        return low, high

    def _get_center(self):
        '''
        Finds the index of the 3d center of the array
        
        Picks the lower-index voxel if there's no true "center"
        '''

        #-1 accounts for python indexing
        center = (self.sz-1)/2
        return center

    def _center_crop(self, vol, shape):
        """
        Crops the passed volume from the center

        Parameters
        ----------
        vol : the array to be croped
        shape : the croped shape

        Returns
        -------
        vol : the croped volume
        """

        sz1 = np.asarray( vol.shape )
        sz2 = np.asarray( shape )
        # offset of both sides
        off1 = (sz1 - sz2+1)/2
        off2 = (sz1 - sz2)/2

        return vol[ off1[0]:-off2[0],\
                    off1[1]:-off2[1],\
                    off1[2]:-off2[2]]

    def _auto_crop(self, arrs):
        """
        crop the list of volumes to make sure that volume sizes are the same.

        Note that this function was not tested yet!!
        """

        if len(arrs) == 1:
            return arrs

        # find minimum size
        splist = list()
        for arr in arrs:
            splist.append( arr.shape )
        sz_min = min( splist )

        # crop every volume
        ret = list()
        for arr in arrs:
            ret.append( self._center_crop( arr, sz_min ) )
        return ret

    def _read_files(self, files):
        """
        read a list of tif files

        Parameters
        ----------
        files : list of string, file names

        Return
        ------
        ret:  list of 3D array, could be different size
        """
        ret = list()
        for fl in files:
            vol = emirt.emio.imread(fl).astype('float32')
            ret.append( vol )
        return ret

    def get_sub_volume(self, arr, dev, rft=[]):
        """
        Returns a 4d subvolume of the original, specified
        by deviation from the center voxel. Performs data
        augmentation if specified by the rft argument

        Parameters
        ----------
        dev : the deviation from the center
        rft : the random transformation rule.
        Return:
        -------
        subvol : the transformed sub volume.
        """

        # the center location
        loc = self.center + dev

        # extract volume
        subvol  = arr[ :,   loc[0]-self.low_setsz[0]  : loc[0] + self.high_setsz[0]+1,\
                            loc[1]-self.low_setsz[1]  : loc[1] + self.high_setsz[1]+1,\
                            loc[2]-self.low_setsz[2]  : loc[2] + self.high_setsz[2]+1]
        # random transformation
        if self.pars['is_data_aug']:
            subvol = self._data_aug_transform(subvol, rft)
        return subvol

    def _data_aug_transform(self, data, rft):
        """
        transform data according to a rule

        Parameters
        ----------
        data : 3D numpy array need to be transformed
        rft : transform rule, specified as an array of bool
            [z-reflection,
            y-reflection,
            x-reflection,
            xy transpose]

        Returns
        -------
        data : the transformed array
        """

        if np.size(rft)==0:
            return data
        # transform every pair of input and label volume

        #z-reflection
        if rft[0]:
            data  = data[:, ::-1, :,    :]
        #y-reflection
        if rft[1]:
            data  = data[:, :,    ::-1, :]
        #x-reflection
        if rft[2]:
            data = data[:,  :,    :,    ::-1]
        #transpose
        if rft[3]:
            data = data.transpose(0,1,3,2)

        return data

class CInputImage(CImage):
    '''
    Subclass of CImage which represents the type of input data seen
    by ZNN neural networks 

    Internally preprocesses the data, and modifies the legal 
    deviation range for affinity data output.
    '''

    def __init__(self, config, pars, sec_name, setsz ):
        CImage.__init__(self, config, pars, sec_name, setsz )

        # preprocessing
        pp_types = config.get(sec_name, 'pp_types').split(',')
        for c in xrange( self.arr.shape[0] ):
            self.arr[c,:,:,:] = self._preprocess(self.arr[c,:,:,:], pp_types[c])

    def _preprocess( self, vol, pp_type):
        if 'standard2D' == pp_type:
            for z in xrange( vol.shape[0] ):
                vol[z,:,:] = (vol[z,:,:] - np.mean(vol[z,:,:])) / np.std(vol[z,:,:])
        elif 'standard3D' == pp_type:
            vol = (vol - np.mean(vol)) / np.std(vol)
        elif 'none' == pp_type or "None" in pp_type:
            return vol
        else:
            raise NameError( 'invalid preprocessing type' )
        return vol

    def get_subvol(self, dev, rft):
        return self.get_sub_volume(self.arr, dev, rft)

    def get_dev_range(self):
        '''Override of the CImage implementation to account
        for affinity preprocessing'''

        low, high = super(CInputImage, self).get_dev_range()

        if 'aff' in self.pars['out_dtype']:
            #Given affinity preprocessing (see _lbl2aff), valid affinity
            # values only exist for the later voxels, which can create
            # boundary issues
            low += 1

        return low, high

class COutputLabel(CImage):
    '''
    Subclass of CImage which represents output labels for
    ZNN neural networks 

    Internally handles preprocessing of the data, and can 
    contain masks for sparsely-labelled training
    '''

    def __init__(self, config, pars, sec_name, setsz):
        CImage.__init__(self, config, pars, sec_name, setsz)

        # Affinity preprocessing decreases the output
        # size by one voxel in each dimension, this counteracts
        # that effect
        if 'aff' in pars['out_dtype']:
            # increase the subvolume size for affinity
            self.setsz += 1
            self.low_setsz  = (self.setsz-1)/2
            self.high_setsz = self.setsz / 2

        # deal with mask
        self.msk = np.array([])
        if config.has_option(sec_name, 'fmasks'):
            fmasks = config.get(sec_name, 'fnames').split(',\n')
            msklist = self._read_files( fmasks )

            if self._is_auto_crop:
                msklist = self._auto_crop( msklist )

            self.msk = np.asarray( msklist )
            # mask 'preprocessing'
            self.msk = (self.msk>0).astype('float32')

            assert(self.arr.shape == self.msk.shape)   
            
        
        if pars['is_rebalance']:
            self._rebalance()
            
        # preprocessing
        self.pp_types = config.get(sec_name, 'pp_types').split(',')        
        self._preprocess()       

    def _preprocess( self ):
        """
        preprocess the 4D image stack.

        Parameters
        ----------
        arr : 3D array,
        """

        assert(len(self.pp_types)==1)

        # loop through volumes
        for c, pp_type in enumerate(self.pp_types):
            if 'none' == pp_type or 'None'==pp_type:
                return
            elif 'binary_class' == pp_type:
                self.arr = self._binary_class(self.arr)
                self.msk = np.tile(self.msk, (2,1,1,1))
                return
            elif 'one_class' == pp_type:
                self.arr = (self.arr>0).astype('float32')
                return
            elif 'aff' in pp_type:
                # affinity preprocessing handled later
                # when fetching subvolumes (get_subvol)
                return
            else:
                raise NameError( 'invalid preprocessing type' )

        return

    def _binary_class(self, lbl):
        """
        Binary-Class Label Transformation
        
        Parameters
        ----------
        lbl : 4D array, label volume.

        Return
        ------
        ret : 4D array, two volume with opposite value
        """
        assert(lbl.shape[0] == 1)

        ret = np.empty((2,)+ lbl.shape[1:4], dtype='float32')

        ret[0, :,:,:] = (lbl[0,:,:,:]>0).astype('float32')
        ret[1:,  :,:,:] = 1 - ret[0, :,:,:]

        return ret

    def get_subvol(self, dev, rft):
        """
        get sub volume for training.

        Parameter
        ---------
        dev : coordinate array, deviation from volume center.
        rft : binary vector, transformation rule

        Return
        ------
        arr : 4D array, could be affinity of binary class
        """
        sublbl = self.get_sub_volume(self.arr, dev, rft)
        submsk = self.get_sub_volume(self.msk, dev, rft)
        if 'aff' in self.pp_types[0]:
            # transform the output volumes to affinity array
            sublbl = self._lbl2aff( sublbl )
            # get the affinity mask
            submsk = self._msk2affmsk( submsk )
            if self.pars['is_rebalance']:
                # apply the rebalance
                submsk = self._rebalance_aff(sublbl, submsk)
        return sublbl, submsk
    
    def _rebalance_aff(self, lbl, msk):
        wts = np.zeros(lbl.shape, dtype='float32')
        wts[0,:,:,:][lbl[0,:,:,:] >0] = self.zwp
        wts[1,:,:,:][lbl[1,:,:,:] >0] = self.ywp
        wts[2,:,:,:][lbl[2,:,:,:] >0] = self.xwp
        
        wts[0,:,:,:][lbl[0,:,:,:]==0] = self.zwz  
        wts[1,:,:,:][lbl[1,:,:,:]==0] = self.ywz
        wts[2,:,:,:][lbl[2,:,:,:]==0] = self.xwz
        if np.size(msk)==0:
            return wts
        else:
            return msk*wts
    
    @autojit
    def _msk2affmsk( self, msk ):
        """
        transform binary mask to affinity mask
        
        Parameters
        ----------
        msk : 4D array, one channel, binary mask for boundary map
        
        Returns
        -------
        ret : 4D array, 3 channel for z,y,x direction
        """
        if np.size(msk)==0:
            return msk
        C,Z,Y,X = msk.shape
        ret = np.zeros((3, Z-1, Y-1, X-1), dtype='float32')
        
        for z in xrange(Z-1):
            for y in xrange(Y-1):
                for x in xrange(X-1):
                    if msk[0,z,y,x]>0:
                        if msk[0,z+1,y,x]>0:
                            ret[0,z,y,x] = 1
                        if msk[0,z,y+1,x]>0:
                            ret[1,z,y,x] = 1
                        if msk[0,z,y,x+1]>0:
                            ret[2,z,y,x] = 1
        return ret
        
    def _lbl2aff( self, lbl ):
        """
        transform labels to affinity.

        Parameters
        ----------
        lbl : 4D float32 array, label volume.

        Returns
        -------
        aff : 4D float32 array, affinity graph.
        """
        # the 3D volume number should be one
        assert( lbl.shape[0] == 1 )

        aff_size = np.asarray(lbl.shape)-1
        aff_size[0] = 3

        aff = np.zeros( tuple(aff_size) , dtype='float32')

        #x-affinity
        aff[0,:,:,:] = (lbl[0,1:,1:,1:] == lbl[0,:-1, 1:  ,1: ]) & (lbl[0,1:,1:,1:]>0)
        #y-affinity
        aff[1,:,:,:] = (lbl[0,1:,1:,1:] == lbl[0,1: , :-1 ,1: ]) & (lbl[0,1:,1:,1:]>0)
        #z-affinity
        aff[2,:,:,:] = (lbl[0,1:,1:,1:] == lbl[0,1: , 1:  ,:-1]) & (lbl[0,1:,1:,1:]>0)

        return aff

    def _get_balance_weight( self, arr ):
        # number of nonzero elements
        num_nz = float( np.count_nonzero(arr) )
        # total number of elements
        num = float( np.size(arr) )

        # weight of positive and zero
        wp = 0.5 * num / num_nz
        wz = 0.5 * num / (num - num_nz)
        return wp, wz
    def _rebalance( self ):
        """
        get rebalance tree_size of gradient.
        make the nonboundary and boundary region have same contribution of training.
        """
        if 'aff' in self.pp_types[0]:
            zlbl = (self.arr[0,1:,1:,1:] != self.arr[0, :-1, 1:,  1:])
            ylbl = (self.arr[0,1:,1:,1:] != self.arr[0, 1:,  :-1, 1:])
            xlbl = (self.arr[0,1:,1:,1:] != self.arr[0, 1:,  1:,  :-1])
            self.zwp, self.zwz = self._get_balance_weight(zlbl)
            self.ywp, self.ywz = self._get_balance_weight(ylbl)
            self.xwp, self.xwz = self._get_balance_weight(xlbl)
        else:
            # positive is non-boundary, zero is boundary
            wnb, wb = self._get_balance_weight(self.arr)
            # give value
            weight = np.empty( self.arr.shape, dtype='float32' )
            weight[self.arr>0]  = wnb
            weight[self.arr==0] = wb
    
            if np.size(self.msk)==0:
                self.msk = weight
            else:
                self.msk = self.msk * weight

class CSample:
    """
    Sample Class, which represents a pair of input and output volume structures
    (as CInputImage and COutputImage respectively) 

    Allows simple interface for procuring matched random samples from all volume
    structures at once

    Designed to be similar with Dataset module of pylearn2
    """
    def __init__(self, config, pars, sample_id, net):

        # Parameter object (dict)
        self.pars = pars

        #Extracting layer info from the network
        info_in  = net.get_inputs()
        info_out = net.get_outputs()

        # Name of the sample within the configuration file
        sec_name = "sample%d" % sample_id

        # init deviation range
        # we need to consolidate this over all input and output volumes
        self.dev_high = np.array([sys.maxsize, sys.maxsize, sys.maxsize])
        self.dev_low  = np.array([-sys.maxint-1, -sys.maxint-1, -sys.maxint-1])

        # Loading input images
        self.inputs = dict()
        for name,setsz in info_in.iteritems():

            #Finding the section of the config file
            imid = config.getint(sec_name, name)
            imsec_name = "image%d" % (imid,)
            
            self.inputs[name] = CInputImage(  config, pars, imsec_name, setsz[1:4] )
            low, high = self.inputs[name].get_dev_range()

            # Deviation bookkeeping
            self.dev_high = np.minimum( self.dev_high, high )
            self.dev_low  = np.maximum( self.dev_low , low  )

        # define output images
        self.outputs = dict()
        for name, setsz in info_out.iteritems():

            #Finding the section of the config file
            imid = config.getint(sec_name, name)
            imsec_name = "label%d" % (imid,)

            self.outputs[name] = COutputLabel( config, pars, imsec_name, setsz[1:4])
            low, high = self.outputs[name].get_dev_range()

            # Deviation bookkeeping
            self.dev_high = np.minimum( self.dev_high, high )
            self.dev_low  = np.maximum( self.dev_low , low  )
        # find the candidate central locations of sample
        

    def get_random_sample(self):
        '''Fetches a matching random sample from all input and output volumes'''

        # random transformation roll
        rft = (np.random.rand(4)>0.5)

        # random deviation from the volume center
        dev = np.empty(3)
        dev[0] = np.random.randint(self.dev_low[0], self.dev_high[0])
        dev[1] = np.random.randint(self.dev_low[1], self.dev_high[1])
        dev[2] = np.random.randint(self.dev_low[2], self.dev_high[2])

        # get input and output 4D sub arrays
        inputs = dict()
        for name, img in self.inputs.iteritems():
            inputs[name] = img.get_subvol(dev, rft)

        outputs = dict()
        msks = dict()
        for name, lbl in self.outputs.iteritems():
            outputs[name], msks[name] = lbl.get_subvol(dev, rft)

        return ( inputs, outputs, msks )

class CSamples:
    def __init__(self, config, pars, ids, net):
        """
        Samples Class - which represents a collection of data samples

        This can be useful when one needs to use multiple collections
        of data for training/testing, or as a generalized interface
        for single collections

        Parameters
        ----------
        config : python parser object, read the config file
        pars : parameters
        ids : set of sample ids
        net: network for which this samples object should be tailored
        """

        #Parameter object
        self.pars = pars

        #Information about the input and output layers
        info_in  = net.get_inputs()
        info_out = net.get_outputs()
        
        self.samples = list()
        for sid in ids:
            sample = CSample(config, pars, sid, net)
            self.samples.append( sample )

    def get_random_sample(self):
        '''Fetches a random sample from a random CSample object'''
        i = np.random.randint( len(self.samples) )
        return self.samples[i].get_random_sample()

    def get_inputs(self, sid):
        return self.samples[sid].get_input()
