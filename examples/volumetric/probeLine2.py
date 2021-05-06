"""Probe a Volume with a line
and plot the intensity values"""
from vedo import *
from vedo.pyplot import plot

vol = Volume(dataurl+'embryo.slc')
vol.addScalarBar3D(title='wild-type mouse embryo', c='k')

p1, p2 = (50,50,50), (200,200,200)
pl = probeLine(vol, p1, p2, res=100).lineWidth(4)

xvals = pl.points()[:,0]
yvals = pl.getPointArray()

plt = plot(xvals, yvals,
           xtitle=" ", ytitle="voxel intensity",
           aspect=16/9,
           spline=True,
           lc="r",       # line color
           marker="*",   # marker style
           mc="dr",      # marker color
           ms=0.9,       # marker size
          )
plt.shift(0,25,0)

show(vol, pl, __doc__, plt, axes=dict(xyGrid=0, yzGrid=0)).close()
# or:
#show([(vol, pl, __doc__), plt], N=2, sharecam=False).close()
