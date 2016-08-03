import healpy as hp
import numpy as np
from catalog import Entry
from utilities import TOTAL_SQDEG, SEC_PER_DEG, astro_to_sphere

_PIXRES = 8

class Mask(object):
	"""Docstring."""

	def __init__(self): pass
	def calc_radmask(self, maskgals, clusters, mpcscale_temp, **kwargs): pass


class HPMask(Mask):
	"""Docstring."""

	def __init__(self, confstr):
		maskinfo, hdr = fitsio.read(confstr.maskfile, ext=1, header=True)
		maskinfo = Entry(maskinfo)
		nlim, nside, nest = maskinfo.hpix.size, hdr['NSIDE'], hdr['NEST']
		hpix_ring = maskinfo.hpix if nest != 1 else None # replace none w/ fn call
		if confstr.pixnum > 0:
			hpix_area = TOTAL_SQDEG/(12 * hdr.nside**2)
			border = confstr.border + 2*np.sqrt(hpix_area)
			# more fn calls to be implemented
			muse = None
		else:
			muse = np.arange(nlim)
		offset, ntot = min(hpix_ring)-1, max(hpix_ring)-min(hpix_ring)+3
		self.nside, self.offset, self.npix = nside, offset, npix
		try:
			self.fracgood_float = 1
			self.fracgood[hpix_ring-offset] = instr[muse].fracgood
		except ValueError:
			self.fracgood_float = 0
			self.fracgood[hpix_ring-offset] = 1

	def calc_radmask(self, maskgals, clusters, mpcscale, 
							bsmaskind = None, bfmaskind = None):
		ras = clusters.ra + maskgals.x/(mpcscale*SEC_PER_DEG)/np.cos(np.radians(clusters.dec))
		decs = clusters.dec + maskgals.y/(mpcscale*SEC_PER_DEG)
		theta, pi = astro_to_sphere(ras, dec)
		# fn calls, var assignments to be implemented
		radmask = np.zeros(ras.size)
		if self.fracgood_float == 0:
			gd = None
			# conftinue implementation
