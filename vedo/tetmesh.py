import vtk
import vedo
import vedo.docs as docs
import vedo.utils as utils
from vedo.base import BaseGrid
from vedo.mesh import Mesh
from vedo.colors import printc
import numpy as np

__doc__ = (
    """
Support for tetrahedral meshes.
"""
    + docs._defs
)

__all__ = ["TetMesh", "delaunay3D", "tetralize"]


##########################################################################
def delaunay3D(mesh, alphaPar=0, tol=None, boundary=False):
    """Create 3D Delaunay triangulation of input points."""
    deln = vtk.vtkDelaunay3D()
    if utils.isSequence(mesh):
        pd = vtk.vtkPolyData()
        vpts = vtk.vtkPoints()
        vpts.SetData(utils.numpy2vtk(mesh, dtype=np.float))
        pd.SetPoints(vpts)
        deln.SetInputData(pd)
    else:
        deln.SetInputData(mesh.GetMapper().GetInput())
    deln.SetAlpha(alphaPar)
    deln.AlphaTetsOn()
    deln.AlphaTrisOff()
    deln.AlphaLinesOff()
    deln.AlphaVertsOff()
    if tol:
        deln.SetTolerance(tol)
    deln.SetBoundingTriangulation(boundary)
    deln.Update()
    m = TetMesh(deln.GetOutput())
    return m


def tetralize(dataset, tetsOnly=True):
    """Tetralize any type of dataset.
    If tetsOnly is True will cull all 1D and 2D cells from the output.

    Return a TetMesh.

    Example:

        .. code-block:: python

            from vedo import *
            ug = loadUnStructuredGrid(datadir+'ugrid.vtk')
            tmesh = tetralize(ug)
            tmesh.write('ugrid.vtu').show(axes=1)
    """
    tt = vtk.vtkDataSetTriangleFilter()
    tt.SetInputData(dataset)
    tt.SetTetrahedraOnly(tetsOnly)
    tt.Update()
    m = TetMesh(tt.GetOutput())
    return m


##########################################################################
class TetMesh(vtk.vtkVolume, BaseGrid):
    """The class describing tetrahedral meshes."""

    def __init__(self, inputobj=None,
                 c=('r','y','lg','lb','b'), #('b','lb','lg','y','r')
                 alpha=(0.5, 1),
                 alphaUnit=1,
                 mapper='tetra',
                 ):

        BaseGrid.__init__(self)

        self.useArray = 0

        #inputtype = str(type(inputobj))
        #printc('TetMesh inputtype', inputtype)

        ###################
        if inputobj is None:
            self._data = vtk.vtkUnstructuredGrid()

        elif isinstance(inputobj, vtk.vtkUnstructuredGrid):
            self._data = inputobj

        elif isinstance(inputobj, vtk.vtkRectilinearGrid):
            r2t = vtk.vtkRectilinearGridToTetrahedra()
            r2t.SetInputData(inputobj)
            r2t.RememberVoxelIdOn()
            r2t.SetTetraPerCellTo6()
            r2t.Update()
            self._data = r2t.GetOutput()

        elif isinstance(inputobj, vtk.vtkDataSet):
            r2t = vtk.vtkDataSetTriangleFilter()
            r2t.SetInputData(inputobj)
            #r2t.TetrahedraOnlyOn()
            r2t.Update()
            self._data = r2t.GetOutput()

        elif isinstance(inputobj, str):
            from vedo.io import download, loadUnStructuredGrid
            if "https://" in inputobj:
                inputobj = download(inputobj, verbose=False)
            ug = loadUnStructuredGrid(inputobj)
            tt = vtk.vtkDataSetTriangleFilter()
            tt.SetInputData(ug)
            tt.SetTetrahedraOnly(True)
            tt.Update()
            self._data = tt.GetOutput()

        elif utils.isSequence(inputobj):
            # if "ndarray" not in inputtype:
            #     inputobj = np.array(inputobj)
            self._data = self._buildtetugrid(inputobj[0], inputobj[1])

        ###################
        if 'tetra' in mapper:
            self._mapper = vtk.vtkProjectedTetrahedraMapper()
        elif 'ray' in mapper:
            self._mapper = vtk.vtkUnstructuredGridVolumeRayCastMapper()
        elif 'zs' in mapper:
            self._mapper = vtk.vtkUnstructuredGridVolumeZSweepMapper()
        elif isinstance(mapper, vtk.vtkMapper):
            self._mapper = mapper
        else:
            printc('Unknown mapper type', [mapper], c='r')
            raise RuntimeError()

        self._mapper.SetInputData(self._data)
        self.SetMapper(self._mapper)
        self.color(c).alpha(alpha)
        if alphaUnit:
            self.GetProperty().SetScalarOpacityUnitDistance(alphaUnit)

        # remember stuff:
        self._color = c
        self._alpha = alpha
        self._alphaUnit = alphaUnit
        #-----------------------------------------------------------

    def _update(self, data):
        self._data = data
        self._mapper.SetInputData(data)
        self._mapper.Modified()
        return self


    def _buildtetugrid(self, points, cells):
        ug = vtk.vtkUnstructuredGrid()

        if len(points) == 0:
            return ug
        if not utils.isSequence(points[0]):
            return ug

        if len(cells) == 0:
            return ug

        if not utils.isSequence(cells[0]):
            tets=[]
            nf=cells[0]+1
            for i, cl in enumerate(cells):
                if i==nf or i==0:
                    k = i+1
                    nf = cl+k
                    cell = [cells[j+k] for j in range(cl)]
                    tets.append(cell)
            cells = tets

        sourcePoints = vtk.vtkPoints()
        varr = utils.numpy2vtk(points, dtype=np.float)
        sourcePoints.SetData(varr)
        ug.SetPoints(sourcePoints)

        sourceTets = vtk.vtkCellArray()
        for f in cells:
            ele = vtk.vtkTetra()
            pid = ele.GetPointIds()
            for i, fi in enumerate(f):
                pid.SetId(i, fi)
            sourceTets.InsertNextCell(ele)
        ug.SetCells(vtk.VTK_TETRA, sourceTets)
        return ug


    def clone(self):
        """Clone the ``TetMesh`` object to yield an exact copy."""
        ugCopy = vtk.vtkUnstructuredGrid()
        ugCopy.DeepCopy(self._data)

        cloned = TetMesh(ugCopy)
        pr = vtk.vtkVolumeProperty()
        pr.DeepCopy(self.GetProperty())
        cloned.SetProperty(pr)

        #assign the same transformation to the copy
        cloned.SetOrigin(self.GetOrigin())
        cloned.SetScale(self.GetScale())
        cloned.SetOrientation(self.GetOrientation())
        cloned.SetPosition(self.GetPosition())

        cloned._mapper.SetScalarMode(self._mapper.GetScalarMode())
        cloned.name = self.name
        return cloned


    def threshold(self, name=None, above=None, below=None, on='cells'):
        """
        Threshold the tetrahedral mesh by a cell scalar value.
        Reduce to only tets which satisfy the threshold limits.
        If ``above==below`` will only select tets with that specific value.
        If ``above > below`` selection range is "flipped" (vtk_version>8).

        :param str on: either name refers to a "cells or "points" array.
        """
        th = vtk.vtkThreshold()
        th.SetInputData(self._data)

        if name is None:
            ns = self.getArrayNames()
            if len(ns['CellData']):
                name=ns['CellData'][0]
                th.SetInputArrayToProcess(0,0,0, 1, name)
            elif len(ns['PointData']):
                name=ns['PointData'][0]
                th.SetInputArrayToProcess(0,0,0, 0, name)
            if name is None:
                printc("threshold(): Cannot find active array. Skip.", c='r')
                return self
        else:
            if on.startswith('c'):
                th.SetInputArrayToProcess(0,0,0, 1, name)
            else:
                th.SetInputArrayToProcess(0,0,0, 0, name)

        if above is not None and below is not None:
            if above > below:
                if vedo.settings.vtk_version[0] >= 9:
                    th.SetInvert(True)
                    th.ThresholdBetween(below, above)
                else:
                    printc("threshold(): in vtk<9, above cannot be larger than below. Skip.", c='r')
                    return self
            else:
                th.ThresholdBetween(above, below)

        elif above is not None:
            th.ThresholdByUpper(above)

        elif below is not None:
            th.ThresholdByLower(below)

        th.Update()
        return self._update(th.GetOutput())


    def decimate(self, scalarsName, fraction=0.5, N=None):
        """
        Downsample the number of tets in a TetMesh to a specified fraction.

        :param float fraction: the desired final fraction of the total.
        :param int N: the desired number of final tets

        .. note:: Setting ``fraction=0.1`` leaves 10% of the original nr of tets.
        """
        decimate = vtk.vtkUnstructuredGridQuadricDecimation()
        decimate.SetInputData(self._data)
        decimate.SetScalarsName(scalarsName)

        if N:  # N = desired number of points
            decimate.SetNumberOfTetsOutput(N)
        else:
            decimate.SetTargetReduction(1-fraction)
        decimate.Update()
        return self._update(decimate.GetOutput())


    def subdvide(self):
        """Increase the number of tets of a TetMesh.
        Subdivide one tetrahedron into twelve for every tetra."""
        sd = vtk.vtkSubdivideTetra()
        sd.SetInputData(self._data)
        sd.Update()
        return self._update(sd.GetOutput())


    def isosurface(self, threshold=True):
        """Return a ``Mesh`` isosurface.

        :param float,list threshold: value or list of values to draw the isosurface(s)
        """
        if not self._data.GetPointData().GetScalars():
            self.mapCellsToPoints()
        scrange = self._data.GetPointData().GetScalars().GetRange()
        cf = vtk.vtkContourFilter() #vtk.vtkContourGrid()
        cf.SetInputData(self._data)

        if utils.isSequence(threshold):
            cf.SetNumberOfContours(len(threshold))
            for i, t in enumerate(threshold):
                cf.SetValue(i, t)
            cf.Update()
        else:
            if threshold is True:
                threshold = (2 * scrange[0] + scrange[1]) / 3.0
                #print('automatic threshold set to ' + utils.precision(threshold, 3), end=' ')
                #print('in [' + utils.precision(scrange[0], 3) + ', ' + utils.precision(scrange[1], 3)+']')
            cf.SetValue(0, threshold)
            cf.Update()

        clp = vtk.vtkCleanPolyData()
        clp.SetInputData(cf.GetOutput())
        clp.Update()
        msh = Mesh(clp.GetOutput(), c=None).phong()
        msh._mapper.SetLookupTable(utils.ctf2lut(self))
        return msh


    def slice(self, origin=(0,0,0), normal=(1,0,0)):
        """Return a 2D slice of the mesh by a plane passing through origin and
        assigned normal."""
        strn = str(normal)
        if strn   ==  "x": normal = (1, 0, 0)
        elif strn ==  "y": normal = (0, 1, 0)
        elif strn ==  "z": normal = (0, 0, 1)
        elif strn == "-x": normal = (-1, 0, 0)
        elif strn == "-y": normal = (0, -1, 0)
        elif strn == "-z": normal = (0, 0, -1)
        plane = vtk.vtkPlane()
        plane.SetOrigin(origin)
        plane.SetNormal(normal)

        cc = vtk.vtkCutter()
        cc.SetInputData(self._data)
        cc.SetCutFunction(plane)
        cc.Update()
        msh = Mesh(cc.GetOutput()).flat().lighting('ambient')
        msh._mapper.SetLookupTable(utils.ctf2lut(self))
        return msh

























