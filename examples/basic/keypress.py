"""Implement a custom function that is triggered by
pressing a keyboard button when the rendering window
is in interactive mode

Place pointer anywhere on the mesh and press c"""
from vedo import *

#############################################################
def myfnc(evt):
    mesh = evt.actor
    # printc('dump event info', evt)
    if not mesh or evt.keyPressed != "c":
        printc("click mesh and press c", c="r")
        return
    printc("mesh :", mesh.filename, c=mesh.color())
    printc("point:", mesh.picked3d, c="v")
    cpt = Point(pos=mesh.picked3d, r=20, c="v").pickable(False)
    plt.add(cpt)

##############################################################
plt = Plotter(axes=1)
plt += Mesh(dataurl+"bunny.obj")
plt += __doc__
plt.addCallback('KeyPress', myfnc)
plt.show().close()
