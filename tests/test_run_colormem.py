from __future__ import division, absolute_import, print_function
from past.builtins import xrange

import matplotlib
matplotlib.use('Agg')

import unittest
import numpy.testing as testing
import numpy as np
import fitsio
import copy
from numpy import random
import time
import tempfile
import shutil
import os
import esutil

from redmapper import Configuration
from redmapper import GalaxyCatalog
from redmapper import RunColormem
from redmapper.calibration import SelectSpecRedGalaxies
from redmapper import Catalog
from redmapper.utilities import redmapper_filename

class RunColormemTestCase(unittest.TestCase):
    """
    """

    def test_run_colormem(self):
        file_path = 'data_for_tests'
        configfile = 'testconfig.yaml'

        config = Configuration(os.path.join(file_path, configfile))

        test_dir = tempfile.mkdtemp(dir='./', prefix='TestRedmapper-')
        config.outpath = test_dir

        # First, we need the red galaxy model

        config.specfile_train = os.path.join(file_path, 'test_dr8_spec.fit')
        config.zrange = [0.1,0.2]

        config.redgalfile = redmapper_filename(config, 'test_redgals')
        config.redgalmodelfile = redmapper_filename(config, 'test_redgalmodel')

        selred = SelectSpecRedGalaxies(config)
        selred.run()

        # Main test...
        config.zmemfile = redmapper_filename(config, 'test_zmem')

        rcm = RunColormem(config)
        rcm.run()
        rcm.output_training()

        # Check that the files are there...
        self.assertTrue(os.path.isfile(config.zmemfile))

        cat = fitsio.read(config.zmemfile, ext=1)

        testing.assert_equal(cat.size, 31)
        testing.assert_array_almost_equal(cat['pcol'][0:3], np.array([0.90800124, 0.90229154, 0.71797204]))

        if os.path.exists(test_dir):
            shutil.rmtree(test_dir, True)

if __name__=='__main__':
    unittest.main()