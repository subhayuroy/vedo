import vtk
import os
import glob
import numpy as np
import time

import vedo
import vedo.utils as utils
import vedo.colors as colors
from vedo.assembly import Assembly
from vedo.mesh import Mesh
from vedo.pointcloud import Points
from vedo.picture import Picture
from vedo.volume import Volume
import vedo.docs as docs
import vedo.settings as settings

__doc__ = (
    """
Submodule to load/write meshes and other objects in different formats,
and other I/O functionalities.
"""
    + docs._defs
)

__all__ = [
    "load",
    "download",
    "gunzip",
    "loadStructuredPoints",
    "loadStructuredGrid",
    "loadRectilinearGrid",
    "loadUnStructuredGrid",
    "loadTransform",
    "writeTransform",
    "write",
    "exportWindow",
    "importWindow",
    "screenshot",
    "ask",
    "Video",
]



def load(inputobj, unpack=True, force=False):
    """
    Load ``Mesh``, ``Volume`` and ``Picture`` objects from file or from the web.

    The output will depend on the file extension. See examples below.
    Unzip on the fly, if it ends with `.gz`.
    Can load an object directly from a URL address.

    :param bool unpack: unpack MultiBlockData into a flat list of objects.
    :param bool force: when downloading a file ignore any previous cached downloads
        and force a new one.

    :Examples:

        .. code-block:: python

            from vedo import datadir, load, show

            # Return a Mesh object
            g = load(datadir+'250.vtk')
            show(g)

            # Return a list of 2 meshes
            g = load([datadir+'250.vtk', datadir+'270.vtk'])
            show(g)

            # Return a list of meshes by reading all files in a directory
            # (if directory contains DICOM files then a Volume is returned)
            g = load('mydicomdir/')
            show(g)

            # Return a Volume. Color/Opacity transfer functions can be specified later.
            g = load(datadir+'embryo.slc')
            g.c(['y','lb','w']).alpha((0.0, 0.4, 0.9, 1)).show()

            # Download a file from a URL address and unzip it on the fly
            g = load('https://vedo.embl.es/examples/panther.stl.gz')
            show(g)
    """
    acts = []
    if utils.isSequence(inputobj):
        flist = inputobj
    elif isinstance(inputobj, str) and inputobj.startswith('https://'):
        flist = [inputobj]
    else:
        flist = sorted(glob.glob(inputobj))

    for fod in flist:

        if fod.startswith('https://'):
            fod = download(fod, force=force, verbose=False)

        if os.path.isfile(fod): ### it's a file

            if fod.endswith('.gz'):
                fod = gunzip(fod)

            a = _load_file(fod, unpack)
            acts.append(a)

        elif os.path.isdir(fod):### it's a directory or DICOM
            flist = os.listdir(fod)
            if '.dcm' in flist[0]: ### it's DICOM
                reader = vtk.vtkDICOMImageReader()
                reader.SetDirectoryName(fod)
                reader.Update()
                image = reader.GetOutput()
                actor = Volume(image)

                actor.info['PixelSpacing'] = reader.GetPixelSpacing()
                actor.info['Width'] = reader.GetWidth()
                actor.info['Height'] = reader.GetHeight()
                actor.info['PositionPatient'] = reader.GetImagePositionPatient()
                actor.info['OrientationPatient'] = reader.GetImageOrientationPatient()
                actor.info['BitsAllocated'] = reader.GetBitsAllocated()
                actor.info['PixelRepresentation'] = reader.GetPixelRepresentation()
                actor.info['NumberOfComponents'] = reader.GetNumberOfComponents()
                actor.info['TransferSyntaxUID'] = reader.GetTransferSyntaxUID()
                actor.info['RescaleSlope'] = reader.GetRescaleSlope()
                actor.info['RescaleOffset'] = reader.GetRescaleOffset()
                actor.info['PatientName'] = reader.GetPatientName()
                actor.info['StudyUID'] = reader.GetStudyUID()
                actor.info['StudyID'] = reader.GetStudyID()
                actor.info['GantryAngle'] = reader.GetGantryAngle()

                acts.append(actor)

            else: ### it's a normal directory
                utils.humansort(flist)
                for ifile in flist:
                    a = _load_file(fod+'/'+ifile, unpack)
                    acts.append(a)
        else:
            colors.printc("\times Error in load(): cannot find", fod, c='r')

    if len(acts) == 1:
        if "numpy" in str(type(acts[0])):
            return acts[0]
        if not acts[0]:
            colors.printc("\times Error in load(): cannot load", inputobj, c='r')
        return acts[0]
    elif len(acts) == 0:
        colors.printc("\times Error in load(): cannot load", inputobj, c='r')
        return None
    else:
        return acts


def _load_file(filename, unpack):
    fl = filename.lower()

    ################################################################# other formats:
    if fl.endswith(".xml") or fl.endswith(".xml.gz") or fl.endswith(".xdmf"):
        # Fenics tetrahedral file
        actor = loadDolfin(filename)
    elif fl.endswith(".neutral") or fl.endswith(".neu"):  # neutral tetrahedral file
        actor = loadNeutral(filename)
    elif fl.endswith(".gmsh"):  # gmesh file
        actor = loadGmesh(filename)
    elif fl.endswith(".pcd"):  # PCL point-cloud format
        actor = loadPCD(filename)
        actor.GetProperty().SetPointSize(2)
    elif fl.endswith(".off"):
        actor = loadOFF(filename)
    elif fl.endswith(".3ds"):  # 3ds format
        actor = load3DS(filename)
    elif fl.endswith(".wrl"):
        importer = vtk.vtkVRMLImporter()
        importer.SetFileName(filename)
        importer.Read()
        importer.Update()
        actors = importer.GetRenderer().GetActors() #vtkActorCollection
        actors.InitTraversal()
        wacts = []
        for i in range(actors.GetNumberOfItems()):
            act = actors.GetNextActor()
            wacts.append(act)
        actor = Assembly(wacts)

        ################################################################# volumetric:
    elif fl.endswith(".tif") or fl.endswith(".slc") or fl.endswith(".vti") \
        or fl.endswith(".mhd") or fl.endswith(".nrrd") or fl.endswith(".nii") \
        or fl.endswith(".dem"):
        img = loadImageData(filename)
        actor = Volume(img)

        ################################################################# 2D images:
    elif fl.endswith(".png") or fl.endswith(".jpg") \
        or fl.endswith(".bmp") or fl.endswith(".jpeg") or fl.endswith(".gif"):
        if ".png" in fl:
            picr = vtk.vtkPNGReader()
        elif ".jpg" in fl or ".jpeg" in fl:
            picr = vtk.vtkJPEGReader()
        elif ".bmp" in fl:
            picr = vtk.vtkBMPReader()
        elif ".gif" in fl:
            from PIL import Image, ImageSequence
            img = Image.open(filename)
            frames = []
            for frame in ImageSequence.Iterator(img):
                a = np.array(frame.convert('RGB').getdata(), dtype=np.uint8)
                a = a.reshape(frame.size[1], frame.size[0],3)
                frames.append(Picture(a))
            return frames

        picr.SetFileName(filename)
        picr.Update()
        actor = Picture(picr.GetOutput())  # object derived from vtk.vtkImageActor()

        ################################################################# multiblock:
    elif fl.endswith(".vtm") or fl.endswith(".vtmb"):
        read = vtk.vtkXMLMultiBlockDataReader()
        read.SetFileName(filename)
        read.Update()
        mb = read.GetOutput()
        if unpack:
            acts = []
            for i in range(mb.GetNumberOfBlocks()):
                b =  mb.GetBlock(i)
                if isinstance(b, (vtk.vtkPolyData,
                                  vtk.vtkUnstructuredGrid,
                                  vtk.vtkStructuredGrid,
                                  vtk.vtkRectilinearGrid)):
                    acts.append(Mesh(b))
                elif isinstance(b, vtk.vtkImageData):
                    acts.append(Volume(b))
                elif isinstance(b, vtk.vtkUnstructuredGrid):
                    acts.append(vedo.UGrid(b))
            return acts
        else:
            return mb

        ################################################################# numpy:
    elif fl.endswith(".npy") or fl.endswith(".npz"):
        acts = loadNumpy(filename)

        if unpack is False:
            return Assembly(acts)
        return acts

    elif fl.endswith(".geojson"):
        return loadGeoJSON(filename)

    elif fl.endswith(".pvd"):
        return loadPVD(filename)

    elif fl.endswith(".pdb"):
        return loadPDB(filename)

        ################################################################# polygonal mesh:
    else:
        if fl.endswith(".vtk"): # read all legacy vtk types

            #output can be:
            # PolyData, StructuredGrid, StructuredPoints, UnstructuredGrid, RectilinearGrid
            reader = vtk.vtkDataSetReader()
            reader.ReadAllScalarsOn()
            reader.ReadAllVectorsOn()
            reader.ReadAllTensorsOn()
            reader.ReadAllFieldsOn()
            reader.ReadAllNormalsOn()
            reader.ReadAllColorScalarsOn()

        elif fl.endswith(".ply"):
            reader = vtk.vtkPLYReader()
        elif fl.endswith(".obj"):
            reader = vtk.vtkOBJReader()
        elif fl.endswith(".stl"):
            reader = vtk.vtkSTLReader()
        elif fl.endswith(".byu") or fl.endswith(".g"):
            reader = vtk.vtkBYUReader()
        elif fl.endswith(".foam"):  # OpenFoam
            reader = vtk.vtkOpenFOAMReader()
        elif fl.endswith(".pvd"):
            reader = vtk.vtkXMLGenericDataObjectReader()
        elif fl.endswith(".vtp"):
            reader = vtk.vtkXMLPolyDataReader()
        elif fl.endswith(".vts"):
            reader = vtk.vtkXMLStructuredGridReader()
        elif fl.endswith(".vtu"):
            reader = vtk.vtkXMLUnstructuredGridReader()
        elif fl.endswith(".vtr"):
            reader = vtk.vtkXMLRectilinearGridReader()
        elif fl.endswith(".pvtk"):
            reader = vtk.vtkPDataSetReader()
        elif fl.endswith(".pvtr"):
            reader = vtk.vtkXMLPRectilinearGridReader()
        elif fl.endswith("pvtu"):
            reader = vtk.vtkXMLPUnstructuredGridReader()
        elif fl.endswith(".txt") or fl.endswith(".xyz"):
            reader = vtk.vtkParticleReader()  # (format is x, y, z, scalar)
        elif fl.endswith(".facet"):
            reader = vtk.vtkFacetReader()
        else:
            return None

        reader.SetFileName(filename)
        reader.Update()
        routput = reader.GetOutput()

        if not routput:
            colors.printc("\noentry Unable to load", filename, c='r')
            return None

        if isinstance(routput, vtk.vtkUnstructuredGrid):
            actor = vedo.TetMesh(routput)

        else:
            actor = Mesh(routput)
            if fl.endswith(".txt") or fl.endswith(".xyz"):
                actor.GetProperty().SetPointSize(4)

    actor.filename = filename
    actor.fileSize, actor.created = fileInfo(filename)
    return actor


def download(url, force=False, verbose=True):
    """Retrieve a file from a url, save it locally and return its path."""

    if not url.startswith('https://'):
        colors.printc('Invalid URL (must start with https):\n', url, c='r')
        return url
    url = url.replace('www.dropbox', 'dl.dropbox')

    if "github.com" in url:
        url = url.replace('/blob/', '/raw/')

    basename = os.path.basename(url)

    if '?' in basename:
        basename = basename.split('?')[0]

    from tempfile import NamedTemporaryFile
    tmp_file = NamedTemporaryFile(delete=False)
    tmp_file.name = os.path.join(os.path.dirname(tmp_file.name),
                                 os.path.basename(basename))

    if force==False and os.path.exists(tmp_file.name):
        if verbose:
            colors.printc("using cached file:", tmp_file.name)
            #colors.printc("     (use force=True to force a new download)")
        return tmp_file.name

    try:
        from urllib.request import urlopen, Request
        req = Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        if verbose:
            colors.printc('reading', basename, 'from',
                          url.split('/')[2][:40],'...', end='')
    except ImportError:
        import urllib2
        import contextlib
        urlopen = lambda url_: contextlib.closing(urllib2.urlopen(url_))
        req = url
        if verbose:
            colors.printc('reading', basename, 'from',
                          url.split('/')[2][:40],'...', end='')

    with urlopen(req) as response, open(tmp_file.name, 'wb') as output:
        output.write(response.read())

    if verbose: colors.printc(' done.')
    return tmp_file.name


def gunzip(filename):
    """Unzip a ``.gz`` file to a temporary file and returns its path."""
    if not filename.endswith('.gz'):
        #colors.printc("gunzip() error: file must end with .gz", c='r')
        return filename
    from tempfile import NamedTemporaryFile
    import gzip

    tmp_file = NamedTemporaryFile(delete=False)
    tmp_file.name = os.path.join(os.path.dirname(tmp_file.name),
                                 os.path.basename(filename).replace('.gz',''))
    inF = gzip.open(filename, "rb")
    outF = open(tmp_file.name, "wb")
    outF.write(inF.read())
    outF.close()
    inF.close()
    return tmp_file.name


def fileInfo(file_path):
    sz, created= "", ""
    if os.path.isfile(file_path):
        file_info = os.stat(file_path)
        num = file_info.st_size
        for x in ['B', 'KB', 'MB', 'GB', 'TB']:
            if num < 1024.0:
                break
            num /= 1024.0
        sz =  "%3.1f%s" % (num, x)
        created = time.ctime(os.path.getmtime(file_path))
    return sz, created


###################################################################
def loadStructuredPoints(filename):
    """Load and return a ``vtkStructuredPoints`` object from file."""
    reader = vtk.vtkStructuredPointsReader()
    reader.SetFileName(filename)
    reader.Update()
    return reader.GetOutput()


def loadStructuredGrid(filename):
    """Load and return a ``vtkStructuredGrid`` object from file."""
    if filename.endswith(".vts"):
        reader = vtk.vtkXMLStructuredGridReader()
    else:
        reader = vtk.vtkStructuredGridReader()
    reader.SetFileName(filename)
    reader.Update()
    return reader.GetOutput()


def loadUnStructuredGrid(filename):
    """Load and return a ``vtkunStructuredGrid`` object from file."""
    if filename.endswith(".vtu"):
        reader = vtk.vtkXMLUnstructuredGridReader()
    else:
        reader = vtk.vtkUnstructuredGridReader()
    reader.SetFileName(filename)
    reader.Update()
    return reader.GetOutput()


def loadRectilinearGrid(filename):
    """Load and return a ``vtkRectilinearGrid`` object from file."""
    if filename.endswith(".vtr"):
        reader = vtk.vtkXMLRectilinearGridReader()
    else:
        reader = vtk.vtkRectilinearGridReader()
    reader.SetFileName(filename)
    reader.Update()
    return reader.GetOutput()


def loadXMLData(filename):
    """Read any type of vtk data object encoded in XML format."""
    reader = vtk.vtkXMLGenericDataObjectReader()
    reader.SetFileName(filename)
    reader.Update()
    return reader.GetOutput()


###################################################################
def load3DS(filename):
    """Load ``3DS`` file format from file. Return an ``Assembly(vtkAssembly)`` object."""
    renderer = vtk.vtkRenderer()
    renWin = vtk.vtkRenderWindow()
    renWin.AddRenderer(renderer)

    importer = vtk.vtk3DSImporter()
    importer.SetFileName(filename)
    importer.ComputeNormalsOn()
    importer.SetRenderWindow(renWin)
    importer.Update()

    actors = renderer.GetActors()  # vtkActorCollection
    acts = []
    for i in range(actors.GetNumberOfItems()):
        a = actors.GetItemAsObject(i)
        acts.append(a)
    del renWin
    return Assembly(acts)


def loadOFF(filename):
    """Read the OFF file format."""
    f = open(filename, "r")
    lines = f.readlines()
    f.close()

    vertices = []
    faces = []
    NumberOfVertices = None
    i = -1
    for text in lines:
        if len(text) == 0:
            continue
        if text == '\n':
            continue
        if "#" in text:
            continue
        if "OFF" in text:
            continue

        ts = text.split()
        n = len(ts)

        if not NumberOfVertices and n > 1:
            NumberOfVertices, NumberOfFaces = int(ts[0]), int(ts[1])
            continue
        i += 1

        if i < NumberOfVertices and n == 3:
            x, y, z = float(ts[0]), float(ts[1]), float(ts[2])
            vertices.append([x, y, z])

        ids = []
        if NumberOfVertices <= i < (NumberOfVertices + NumberOfFaces + 1) and n > 2:
            ids += [int(xx) for xx in ts[1:]]
            faces.append(ids)

    return Mesh(utils.buildPolyData(vertices, faces))


def loadGeoJSON(filename):
    """Load GeoJSON files."""
    jr = vtk.vtkGeoJSONReader()
    jr.SetFileName(filename)
    jr.Update()
    return Mesh(jr.GetOutput())


def loadDolfin(filename, exterior=False):
    """Reads a `Fenics/Dolfin` file format (.xml or .xdmf).
    Return an ``Mesh`` object."""
    import sys
    if sys.version_info[0] < 3:
        return _loadDolfin_old(filename)

    import dolfin

    if filename.lower().endswith('.xdmf'):
        f = dolfin.XDMFFile(filename)
        m = dolfin.Mesh()
        f.read(m)
    else:
        m = dolfin.Mesh(filename)

    bm = dolfin.BoundaryMesh(m, "exterior")

    if exterior:
        poly = utils.buildPolyData(bm.coordinates(), bm.cells(), fast=True, tetras=True)
    else:
        polyb = utils.buildPolyData(bm.coordinates(), bm.cells(), fast=True, tetras=True)
        polym = utils.buildPolyData(m.coordinates(), m.cells(), fast=True, tetras=True)
        app = vtk.vtkAppendPolyData()
        app.AddInputData(polym)
        app.AddInputData(polyb)
        app.Update()
        poly = app.GetOutput()
    return Mesh(poly).lw(0.1)


def _loadDolfin_old(filename, exterior='dummy'):
    import xml.etree.ElementTree as et

    if filename.endswith(".gz"):
        import gzip

        inF = gzip.open(filename, "rb")
        outF = open("/tmp/filename.xml", "wb")
        outF.write(inF.read())
        outF.close()
        inF.close()
        tree = et.parse("/tmp/filename.xml")
    else:
        tree = et.parse(filename)

    coords, faces = [], []
    for mesh in tree.getroot():
        for elem in mesh:
            for e in elem.findall("vertex"):
                x = float(e.get("x"))
                y = float(e.get("y"))
                ez = e.get("z")
                if ez is None:
                    coords.append([x, y])
                else:
                    z = float(ez)
                    coords.append([x, y, z])

            tets = elem.findall("tetrahedron")
            if not len(tets):
                tris = elem.findall("triangle")
                for e in tris:
                    v0 = int(e.get("v0"))
                    v1 = int(e.get("v1"))
                    v2 = int(e.get("v2"))
                    faces.append([v0, v1, v2])
            else:
                for e in tets:
                    v0 = int(e.get("v0"))
                    v1 = int(e.get("v1"))
                    v2 = int(e.get("v2"))
                    v3 = int(e.get("v3"))
                    faces.append([v0, v1, v2, v3])

    poly = utils.buildPolyData(coords, faces)
    return Mesh(poly)


def loadPVD(filename):
    """Reads a paraview set of files."""
    import xml.etree.ElementTree as et

    tree = et.parse(filename)

    dname = os.path.dirname(filename)
    if not dname:
        dname = '.'

    listofobjs = []
    for coll in tree.getroot():
        for dataset in coll:
            fname = dataset.get("file")
            ob = load(dname+'/'+fname)
            tm = dataset.get("timestep")
            if tm:
                ob.time(tm)
            listofobjs.append(ob)
    if len(listofobjs) == 1:
        return listofobjs[0]
    elif len(listofobjs) == 0:
        return None
    else:
        return listofobjs


def loadPDB(filename, bondScale=1, hydrogenBondScale=1, coilWidth=0.3, helixWidth=1.3):
    """Reads a molecule Protein Data Bank file."""
    rr = vtk.vtkPDBReader()
    rr.SetFileName('1btn.pdb')
    rr.SetBScale(bondScale)
    rr.SetHBScale(hydrogenBondScale)
    rr.Update()
    prf = vtk.vtkProteinRibbonFilter()
    prf.SetCoilWidth(coilWidth)
    prf.SetHelixWidth(helixWidth)
    prf.SetInputData(rr.GetOutput())
    prf.Update()
    return Mesh(prf.GetOutput())


def loadNeutral(filename):
    """Reads a `Neutral` tetrahedral file format. Return an ``Mesh`` object."""
    f = open(filename, "r")
    lines = f.readlines()
    f.close()

    ncoords = int(lines[0])
    coords = []
    for i in range(1, ncoords + 1):
        x, y, z = lines[i].split()
        coords.append([float(x), float(y), float(z)])

    ntets = int(lines[ncoords + 1])
    idolf_tets = []
    for i in range(ncoords + 2, ncoords + ntets + 2):
        text = lines[i].split()
        v0, v1, v2, v3 = int(text[1])-1, int(text[2])-1, int(text[3])-1, int(text[4])-1
#        p0, p1, p2, p3 = np.array(coords[v1]), np.array(coords[v0]), coords[v3], coords[v2]
#        d10 = p1-p0
#        d21 = p2-p1
#        dc = np.cross(d10, d21)
#        print(np.dot(dc,p3-p0))
        idolf_tets.append([v0, v1, v2, v3])

    poly = utils.buildPolyData(coords, idolf_tets)
    return Mesh(poly)


def loadGmesh(filename):
    """Reads a `gmesh` file format. Return an ``Mesh`` object."""
    f = open(filename, "r")
    lines = f.readlines()
    f.close()

    nnodes = 0
    index_nodes = 0
    for i, line in enumerate(lines):
        if "$Nodes" in line:
            index_nodes = i + 1
            nnodes = int(lines[index_nodes])
            break
    node_coords = []
    for i in range(index_nodes + 1, index_nodes + 1 + nnodes):
        cn = lines[i].split()
        node_coords.append([float(cn[1]), float(cn[2]), float(cn[3])])

    nelements = 0
    index_elements = 0
    for i, line in enumerate(lines):
        if "$Elements" in line:
            index_elements = i + 1
            nelements = int(lines[index_elements])
            break
    elements = []
    for i in range(index_elements + 1, index_elements + 1 + nelements):
        ele = lines[i].split()
        elements.append([int(ele[-3]), int(ele[-2]), int(ele[-1])])

    poly = utils.buildPolyData(node_coords, elements, indexOffset=1)
    return Mesh(poly)


def loadPCD(filename):
    """Return a ``Mesh`` made of only vertex points
    from `Point Cloud` file format. Return an ``Points`` object."""
    f = open(filename, "r")
    lines = f.readlines()
    f.close()
    start = False
    pts = []
    N, expN = 0, 0
    for text in lines:
        if start:
            if N >= expN:
                break
            l = text.split()
            pts.append([float(l[0]), float(l[1]), float(l[2])])
            N += 1
        if not start and "POINTS" in text:
            expN = int(text.split()[1])
        if not start and "DATA ascii" in text:
            start = True
    if expN != N:
        colors.printc("Mismatch in pcd file", expN, len(pts), c="red")
    poly = utils.buildPolyData(pts)
    return Points(poly).pointSize(4)


def toNumpy(obj):
    '''Dump a vedo object to numpy format.'''

    adict = dict()
    adict['type'] = 'unknown'

    ########################################################
    def _fillcommon(obj, adict):
        adict['filename'] = obj.filename
        adict['name'] = obj.name
        adict['time'] = obj.time()
        adict['rendered_at'] = obj.renderedAt
        adict['position'] = obj.pos()
        adict['info'] = obj.info
        m = np.eye(4)
        vm = obj.getTransform().GetMatrix()
        for i in [0, 1, 2, 3]:
            for j in [0, 1, 2, 3]:
                m[i,j] = vm.GetElement(i, j)
        adict['transform'] = m
        minv = np.eye(4)
        vm.Invert()
        for i in [0, 1, 2, 3]:
            for j in [0, 1, 2, 3]:
                minv[i,j] = vm.GetElement(i, j)
        adict['transform_inverse'] = minv

    ########################################################
    def _fillmesh(obj, adict):

        adict['points'] = obj.points(transformed=False).astype(np.float32)
        poly = obj.polydata()
        adict['flagText'] = obj.flagText

        adict['cells'] = None
        if poly.GetNumberOfPolys():
            try:
                adict['cells'] = np.array(obj.faces(), dtype=np.uint32)
            except ValueError:
                adict['cells'] = obj.faces()

        adict['lines'] = None
        if poly.GetNumberOfLines():
            adict['lines'] = obj.lines()

        adict['pointdata'] = []
        for iname in obj.getArrayNames()['PointData']:
            if 'Normals' in iname.lower(): continue
            arr = poly.GetPointData().GetArray(iname)
            adict['pointdata'].append([utils.vtk2numpy(arr), iname])
        adict['celldata'] = []
        for iname in obj.getArrayNames()['CellData']:
            if 'Normals' in iname.lower(): continue
            arr = poly.GetCellData().GetArray(iname)
            adict['celldata'].append([utils.vtk2numpy(arr), iname])

        adict['activedata'] = None
        if poly.GetPointData().GetScalars():
            adict['activedata'] = ['pointdata', poly.GetPointData().GetScalars().GetName()]
        elif poly.GetCellData().GetScalars():
            adict['activedata'] = ['celldata',  poly.GetCellData().GetScalars().GetName()]

        adict['LUT'] = None
        adict['LUT_range'] = None
        lut = obj._mapper.GetLookupTable()
        if lut:
            nlut = lut.GetNumberOfTableValues()
            lutvals=[]
            for i in range(nlut):
                v4 = lut.GetTableValue(i) # r, g, b, alpha
                lutvals.append(v4)
            adict['LUT'] = lutvals
            adict['LUT_range'] = lut.GetRange()

        prp = obj.GetProperty()
        adict['alpha'] = prp.GetOpacity()
        adict['representation'] = prp.GetRepresentation()
        adict['pointsize'] = prp.GetPointSize()

        adict['linecolor'] = None
        adict['linewidth'] = None
        if prp.GetEdgeVisibility():
            adict['linewidth'] = obj.lineWidth()
            adict['linecolor'] = obj.lineColor()

        adict['ambient'] = prp.GetAmbient()
        adict['diffuse'] = prp.GetDiffuse()
        adict['specular'] = prp.GetSpecular()
        adict['specularpower'] = prp.GetSpecularPower()
        adict['specularcolor'] = prp.GetSpecularColor()
        adict['shading'] = prp.GetInterpolation()
        adict['color'] = prp.GetColor()
        adict['lightingIsOn'] = prp.GetLighting()
        adict['backColor'] = None
        if obj.GetBackfaceProperty():
            adict['backColor'] = obj.GetBackfaceProperty().GetColor()

        adict['scalarvisibility'] = obj.mapper().GetScalarVisibility()

        adict['texture'] = None

    ######################################################## Mesh
    if isinstance(obj, Points):
        adict['type'] = 'Mesh'
        _fillcommon(obj, adict)
        _fillmesh(obj, adict)

    ######################################################## Assembly
    elif isinstance(obj, Assembly):
        pass
        # adict['type'] = 'Assembly'
        # _fillcommon(obj, adict)
        # adict['actors'] = []
        # for a in obj.unpack():
        #     assdict = dict()
        #     if isinstance(a, Mesh):
        #         _fillmesh(a, assdict)
        #         adict['actors'].append(assdict)

    ######################################################## Volume
    elif isinstance(obj, Volume):
        adict['type'] = 'Volume'
        _fillcommon(obj, adict)
        imgdata = obj.inputdata()
        arr = utils.vtk2numpy(imgdata.GetPointData().GetScalars())
        adict['array'] = arr.reshape(imgdata.GetDimensions())
        adict['mode'] = obj.mode()
        #adict['jittering'] = obj.mapper().GetUseJittering()

        prp = obj.GetProperty()
        ctf = prp.GetRGBTransferFunction()
        otf = prp.GetScalarOpacity()
        gotf = prp.GetGradientOpacity()
        smin, smax = ctf.GetRange()
        xs = np.linspace(smin, smax, num=100, endpoint=True)
        cols, als, algrs = [], [], []
        for x in xs:
            cols.append(ctf.GetColor(x))
            als.append(otf.GetValue(x))
            if gotf:
                algrs.append(gotf.GetValue(x))
        adict['color'] = cols
        adict['alpha'] = als
        adict['alphagrad'] = algrs

    ######################################################## Picture
    elif isinstance(obj, Picture):
        adict['type'] = 'Picture'
        _fillcommon(obj, adict)
        adict['array'] = utils.vtk2numpy(obj.inputdata().GetPointData().GetScalars())
        adict['shape'] = obj.inputdata().GetDimensions()
        print('toNumpy(): vedo.Picture', obj.shape, obj.GetPosition())

    ######################################################## Text2D
    elif isinstance(obj, vedo.Text2D):
        adict['type'] = 'Text2D'
        adict['rendered_at'] = obj.renderedAt
        adict['text'] = obj.text()
        adict['position'] = obj.GetPosition()
        adict['color'] = obj.property.GetColor()
        adict['font'] =  obj.font()
        adict['size']  = obj.property.GetFontSize()/22.5
        adict['bgcol'] = obj.property.GetBackgroundColor()
        adict['alpha'] = obj.property.GetBackgroundOpacity()
        adict['frame'] = obj.property.GetFrame()
        # print('toNumpy(): vedo.Text2D', obj.text()[:10], obj.font(), obj.GetPosition())

    else:
        pass
        #colors.printc('Unknown object type in toNumpy()', [obj], c='r')

    return adict


def loadNumpy(inobj):
    """Load a vedo format file or scene."""

    # make sure the numpy file is not containing a scene
    if isinstance(inobj, str): # user passing a file

        if inobj.endswith('.npy'):
            data = np.load(inobj, allow_pickle=True, encoding='latin1')#.flatten()
        elif  inobj.endswith('.npz'):
            data = np.load(inobj, allow_pickle=True)['vedo_scenes']

        isdict = hasattr(data[0], "keys")

        if isdict and "objects" in data[0].keys():  # loading a full scene!!
            return importWindow(data[0])

        # it's a very normal numpy data object? just return it!
        if not isdict:
            return data
        if 'type' not in data[0].keys():
            return data

    else:
        data = inobj


    ######################################################
    def _loadcommon(obj, d):
        keys = d.keys()
        if 'time' in keys: obj.time(d['time'])
        if 'name' in keys: obj.name = d['name']
        if 'filename' in keys: obj.filename = d['filename']

        if 'transform' in keys and len(d['transform']) == 4:
            vm = vtk.vtkMatrix4x4()
            for i in [0, 1, 2, 3]:
               for j in [0, 1, 2, 3]:
                   vm.SetElement(i, j, d['transform'][i,j])
            obj.applyTransform(vm)
        elif 'position' in keys:
            obj.pos(d['position'])

    ######################################################
    def _buildmesh(d):
        keys = d.keys()

        vertices = d['points']
        if not len(vertices):
            return None

        cells = None
        if 'cells' in keys:
            cells = d['cells']

        lines = None
        if 'lines' in keys:
            lines = d['lines']

        poly = utils.buildPolyData(vertices, cells, lines)
        msh = Mesh(poly)
        _loadcommon(msh, d)

        prp = msh.GetProperty()
        if 'ambient' in keys:        prp.SetAmbient(d['ambient'])
        if 'diffuse' in keys:        prp.SetDiffuse(d['diffuse'])
        if 'specular' in keys:       prp.SetSpecular(d['specular'])
        if 'specularpower' in keys:  prp.SetSpecularPower(d['specularpower'])
        if 'specularcolor' in keys:  prp.SetSpecularColor(d['specularcolor'])
        if 'lightingIsOn' in keys:   prp.SetLighting(d['lightingIsOn'])
        if 'shading' in keys:        prp.SetInterpolation(d['shading'])
        if 'alpha' in keys:          prp.SetOpacity(d['alpha'])
        if 'opacity' in keys:        prp.SetOpacity(d['opacity']) # synonym
        if 'representation' in keys: prp.SetRepresentation(d['representation'])
        if 'pointsize' in keys and d['pointsize']: prp.SetPointSize(d['pointsize'])

        if 'linewidth' in keys and d['linewidth']: msh.lineWidth(d['linewidth'])
        if 'linecolor' in keys and d['linecolor']: msh.lineColor(d['linecolor'])

        if 'color' in keys and d['color'] is not None:
            msh.color(d['color'])
        if 'backColor' in keys and d['backColor'] is not None:
            msh.backColor(d['backColor'])

        if 'flagText' in keys and d['flagText']:   msh.flag(d['flagText'])

        if 'celldata' in keys:
            for csc, cscname in d['celldata']:
                msh.addCellArray(csc, cscname)
        if 'pointdata' in keys:
            for psc, pscname in d['pointdata']:
                msh.addPointArray(psc, pscname)
        msh.mapper().ScalarVisibilityOff()     # deactivate scalars

        if 'LUT' in keys and 'activedata' in keys and d['activedata']:
            # print(d['activedata'],'', msh.filename)
            lut_list = d['LUT']
            ncols = len(lut_list)
            lut = vtk.vtkLookupTable()
            lut.SetNumberOfTableValues(ncols)
            lut.SetRange(d['LUT_range'])
            for i in range(ncols):
                r, g, b, a = lut_list[i]
                lut.SetTableValue(i, r, g, b, a)
            lut.Build()
            msh.mapper().SetLookupTable(lut)
            msh.mapper().ScalarVisibilityOn()  # activate scalars
            msh.mapper().SetScalarRange(d['LUT_range'])
            if d['activedata'][0] == 'celldata':
                poly.GetCellData().SetActiveScalars(d['activedata'][1])
            if d['activedata'][0] == 'pointdata':
                poly.GetPointData().SetActiveScalars(d['activedata'][1])

        if 'shading' in keys and int(d['shading'])>0:
            msh.computeNormals(cells=0) # otherwise cannot renderer phong

        if 'scalarvisibility' in keys:
            if d['scalarvisibility']:
                msh.mapper().ScalarVisibilityOn()
            else:
                msh.mapper().ScalarVisibilityOff()

        if 'texture' in keys and d['texture']:
            msh.texture(d['texture'])

        return msh
    ######################################################

    objs = []
    for d in data:
        #print('loadNumpy:', d)

        ### Mesh
        if 'mesh' == d['type'].lower():
            a = _buildmesh(d)
            if a: objs.append(a)

        ### Assembly
        elif 'assembly' == d['type'].lower():
            assacts = []
            for ad in d['actors']:
                assacts.append(_buildmesh(ad))
            asse = Assembly(assacts)
            _loadcommon(asse, d)
            objs.append(asse)

        ### Volume
        elif 'volume' == d['type'].lower():
            vol = Volume(d['array'])
            _loadcommon(vol, d)
            if 'jittering' in d.keys(): vol.jittering(d['jittering'])
            #print(d['mode'])
            vol.mode(d['mode'])
            vol.color(d['color'])
            vol.alpha(d['alpha'])
            vol.alphaGradient(d['alphagrad'])
            objs.append(vol)

        ### Picture
        elif 'picture' == d['type'].lower():
            shp = d['shape'][1], d['shape'][0]
            arr0 = d['array']
            rcv = arr0[:,0].reshape(shp)
            rcv = np.flip(rcv, 0)
            gcv = arr0[:,1].reshape(shp)
            gcv = np.flip(gcv, 0)
            bcv = arr0[:,2].reshape(shp)
            bcv = np.flip(bcv, 0)
            arr = np.array([rcv, gcv, bcv])
            arr = np.swapaxes(arr, 0, 2)
            arr = np.swapaxes(arr, 0, 1)
            vimg = Picture(arr)
            _loadcommon(vimg, d)
            objs.append(vimg)

        ### Text2D
        elif 'text2d' == d['type'].lower():
            t = vedo.shapes.Text2D(d['text'], font=d['font'], c=d['color'])
            t.pos(d['position']).size(d['size'])
            t.background(d['bgcol'], d['alpha'])
            if d['frame']:
                t.frame(d['bgcol'])
            objs.append(t)

        ### Annotation ## backward compatibility - will disappear
        elif 'annotation' == d['type'].lower():
            from vedo.shapes import Text2D
            pos = d['position']
            if isinstance(pos, int):
                pos = "top-left"
                d['size'] *= 2.7
            t = Text2D(d['text'], font=d['font'], c=d['color']).pos(pos)
            t.background(d['bgcol'], d['alpha']).size(d['size']).frame(d['bgcol'])
            objs.append(t) ## backward compatibility

    if len(objs) == 1:
        return objs[0]
    elif len(objs) == 0:
        return None
    else:
        return objs


def loadImageData(filename):
    """Read and return a ``vtkImageData`` object from file.
    Use ``load`` instead.
    E.g. `img = load('myfile.tif').imagedata()`
    """
    if ".tif" in filename.lower():
        reader = vtk.vtkTIFFReader()
        # print("GetOrientationType ", reader.GetOrientationType())
        reader.SetOrientationType(settings.tiffOrientationType)
    elif ".slc" in filename.lower():
        reader = vtk.vtkSLCReader()
        if not reader.CanReadFile(filename):
            colors.printc("\prohibited Sorry bad slc file " + filename, c='r')
            return None
    elif ".vti" in filename.lower():
        reader = vtk.vtkXMLImageDataReader()
    elif ".mhd" in filename.lower():
        reader = vtk.vtkMetaImageReader()
    elif ".dem" in filename.lower():
        reader = vtk.vtkDEMReader()
    elif ".nii" in filename.lower():
        reader = vtk.vtkNIFTIImageReader()
    elif ".nrrd" in filename.lower():
        reader = vtk.vtkNrrdReader()
        if not reader.CanReadFile(filename):
            colors.printc("\prohibited Sorry bad nrrd file " + filename, c='r')
            return None
    reader.SetFileName(filename)
    reader.Update()
    image = reader.GetOutput()
    return image



###########################################################
def write(objct, fileoutput, binary=True):
    """
    Write 3D object to file. (same as `save()`).

    Possile extensions are:
        - vtk, vti, npy, npz, ply, obj, stl, byu, vtp, vti, mhd, xyz, tif, png, bmp.
    """
    obj = objct
    if isinstance(obj, Points): # picks transformation
        obj = objct.polydata(True)
    elif isinstance(obj, (vtk.vtkActor, vtk.vtkVolume)):
        obj = objct.GetMapper().GetInput()
    elif isinstance(obj, (vtk.vtkPolyData, vtk.vtkImageData)):
        obj = objct

    if hasattr(obj, 'filename'):
        obj.filename = fileoutput

    fr = fileoutput.lower()
    if   fr.endswith(".vtk"):
        writer = vtk.vtkDataSetWriter()
    elif fr.endswith(".ply"):
        writer = vtk.vtkPLYWriter()
        writer.AddComment("PLY file generated by vedo")
        lut = objct.GetMapper().GetLookupTable()
        if lut:
            pscal = obj.GetPointData().GetScalars()
            if not pscal:
                pscal = obj.GetCellData().GetScalars()
            if pscal and pscal.GetName():
                writer.SetArrayName(pscal.GetName())
            writer.SetLookupTable(lut)
    elif fr.endswith(".stl"):
        writer = vtk.vtkSTLWriter()
    elif fr.endswith(".vtp"):
        writer = vtk.vtkXMLPolyDataWriter()
    elif fr.endswith(".vtu"):
        writer = vtk.vtkXMLUnstructuredGridWriter()
    elif fr.endswith(".vtm"):
        g = vtk.vtkMultiBlockDataGroupFilter()
        for ob in objct:
            if isinstance(ob, (Points, Volume)): # picks transformation
                ob = ob.polydata(True)
                g.AddInputData(ob)
            # elif isinstance(ob, (vtk.vtkActor, vtk.vtkVolume)):
            #     ob = ob.GetMapper().GetInput()
            #     g.AddInputData(ob)
        g.Update()
        mb = g.GetOutputDataObject(0)
        wri = vtk.vtkXMLMultiBlockDataWriter()
        wri.SetInputData(mb)
        wri.SetFileName(fileoutput)
        wri.Write()
        return mb
    elif fr.endswith(".xyz"):
        writer = vtk.vtkSimplePointsWriter()
    elif fr.endswith(".facet"):
        writer = vtk.vtkFacetWriter()
    elif fr.endswith(".tif"):
        writer = vtk.vtkTIFFWriter()
        # print("GetCompression ", writer.GetCompression ())
        writer.SetFileDimensionality(len(obj.GetDimensions()))
    elif fr.endswith(".vti"):
        writer = vtk.vtkXMLImageDataWriter()
    elif fr.endswith(".mhd"):
        writer = vtk.vtkMetaImageWriter()
    elif fr.endswith(".nii"):
        writer = vtk.vtkNIFTIImageWriter()
    elif fr.endswith(".png"):
        writer = vtk.vtkPNGWriter()
    elif fr.endswith(".jpg"):
        writer = vtk.vtkJPEGWriter()
    elif fr.endswith(".bmp"):
        writer = vtk.vtkBMPWriter()
    elif fr.endswith(".npy") or fr.endswith(".npz"):
        if utils.isSequence(objct):
            objslist = objct
        else:
            objslist = [objct]
        dicts2save = []
        for obj in objslist:
            dicts2save.append( toNumpy(obj) )
        np.save(fileoutput, dicts2save)
        return dicts2save

    elif fr.endswith(".obj"):
        outF = open(fileoutput, "w")
        outF.write('# OBJ file format with ext .obj\n')
        outF.write('# File generated by vedo\n')

        for p in objct.points():
            outF.write("v {:.5g} {:.5g} {:.5g}\n".format(*p))

        # pdata = objct.polydata().GetPointData().GetScalars()
        # if pdata:
        #     ndata = vtk_to_numpy(pdata)
        #     for vd in ndata:
        #         outF.write('vp '+ str(vd) +'\n')

        #ptxt = objct.polydata().GetPointData().GetTCoords() # not working
        #if ptxt:
        #    ntxt = vtk_to_numpy(ptxt)
        #    print(len(objct.faces()), objct.points().shape, ntxt.shape)
        #    for vt in ntxt:
        #        outF.write('vt '+ str(vt[0]) +" "+ str(vt[1])+ ' 0\n')

        for i,f in enumerate(objct.faces()):
            fs = ''
            for fi in f:
                fs += " {:d}".format(fi+1)
            outF.write('f' + fs + '\n')

        for l in objct.lines():
            ls = ''
            for li in l:
                ls += str(li+1)+" "
            outF.write('l '+ ls + '\n')

        outF.close()
        return objct

    elif fr.endswith(".xml"):  # write tetrahedral dolfin xml
        vertices = objct.points().astype(str)
        faces = np.array(objct.faces()).astype(str)
        ncoords = vertices.shape[0]
        outF = open(fileoutput, "w")
        outF.write('<?xml version="1.0" encoding="UTF-8"?>\n')
        outF.write('<dolfin xmlns:dolfin="http://www.fenicsproject.org">\n')

        if len(faces[0]) == 4:# write tetrahedral mesh
            ntets = faces.shape[0]
            outF.write('  <mesh celltype="tetrahedron" dim="3">\n')
            outF.write('    <vertices size="' + str(ncoords) + '">\n')
            for i in range(ncoords):
                x, y, z = vertices[i]
                outF.write('      <vertex index="'+str(i)+'" x="'+x+'" y="'+y+'" z="'+z+'"/>\n')
            outF.write('    </vertices>\n')
            outF.write('    <cells size="' + str(ntets) + '">\n')
            for i in range(ntets):
                v0, v1, v2, v3 = faces[i]
                outF.write('     <tetrahedron index="'+str(i)
                           + '" v0="'+v0+'" v1="'+v1+'" v2="'+v2+'" v3="'+v3+'"/>\n')

        elif len(faces[0]) == 3:# write triangle mesh
            ntri = faces.shape[0]
            outF.write('  <mesh celltype="triangle" dim="2">\n')
            outF.write('    <vertices size="' + str(ncoords) + '">\n')
            for i in range(ncoords):
                x, y, dummy_z = vertices[i]
                outF.write('      <vertex index="'+str(i)+'" x="'+x+'" y="'+y+'"/>\n')
            outF.write('    </vertices>\n')
            outF.write('    <cells size="' + str(ntri) + '">\n')
            for i in range(ntri):
                v0, v1, v2 = faces[i]
                outF.write('     <triangle index="'+str(i)+'" v0="'+v0+'" v1="'+v1+'" v2="'+v2+'"/>\n')

        outF.write('    </cells>\n')
        outF.write("  </mesh>\n")
        outF.write("</dolfin>\n")
        outF.close()
        return objct

    else:
        colors.printc("\noentry Unknown format", fileoutput, "file not saved.", c="r")
        return objct

    try:
        if hasattr(writer, 'SetFileTypeToBinary'):
            if binary:
                writer.SetFileTypeToBinary()
            else:
                writer.SetFileTypeToASCII()
        writer.SetInputData(obj)
        writer.SetFileName(fileoutput)
        writer.Write()
    except Exception as e:
        colors.printc("\noentry Error saving: " + fileoutput, "\n", e, c="r")
    return objct


def writeTransform(inobj, filename='transform.mat', comment=''):
    """
    Save a transformation for a mesh or pointcloud to ASCII file.

    Parameters
    ----------
    filename : str, optional
        output file name. The default is 'transform.mat'.
    comment : str, optional
        some optional comment. The default is ''.

    Returns
    -------
    None.
    """
    if isinstance(inobj, Points):
        M = inobj.getTransform().GetMatrix()
    elif isinstance(inobj, vtk.vtkTransform):
        M = inobj.GetMatrix()
    elif isinstance(inobj, vtk.vtkMatrix4x4):
        M = inobj
    else:
        colors.printc("Error in io.writeTransform: cannot understand input type",
                      type(inobj), c='r')
    with open(filename,'w') as f:
        if comment:
            f.write('#'+comment+'\n')
        for i in range(4):
            f.write( str(M.GetElement(i,0))+' '+
                     str(M.GetElement(i,1))+' '+
                     str(M.GetElement(i,2))+' '+
                     str(M.GetElement(i,3))+'\n',
                    )
        f.write('\n')
    return

def loadTransform(filename):
    """
    Load a ``vtkTransform`` from a file.mat.

    Returns
    -------
    T : vtkTransform
        The transformation to be applied to some object (``use applyTransform()``).
    comment : str
        a comment string associated to this transformation file.
    """
    with open(filename,'r') as f:
        lines = f.readlines()
        M = vtk.vtkMatrix4x4()
        i=0
        comment = ''
        for l in lines:
            if l.startswith('#'):
                comment = l.replace('#', "").replace('\n', "")
                continue
            vals = l.split(' ')
            if len(vals)==4:
                for j in range(4):
                    v = vals[j].replace('\n', '')
                    M.SetElement(i,j, float(v))
                i+=1
        T = vtk.vtkTransform()
        T.SetMatrix(M)
    return (T, comment)


###############################################################################
def exportWindow(fileoutput, binary=False):
    '''
    Exporter which writes out the renderered scene into an HTML, X3D
    or Numpy file.

    |export_x3d| |export_x3d.py|_

        `generated webpage <https://vedo.embl.es/examples/embryo.html>`_

        See also: FEniCS test `webpage <https://vedo.embl.es/examples/fenics_elasticity.html>`_.

    .. note:: the rendering window can also be exported to `numpy` file `scene.npz`
        by pressing ``E`` keyboard at any moment during visualization.
    '''
    fr = fileoutput.lower()

    ####################################################################
    if fr.endswith(".npy") or fr.endswith(".npz"):
        sdict = dict()
        vp = settings.plotter_instance
        sdict['shape'] = vp.shape #todo
        sdict['sharecam'] = vp.sharecam #todo
        sdict['camera'] = dict( pos=vp.camera.GetPosition(),
                                focalPoint=vp.camera.GetFocalPoint(),
                                viewup=vp.camera.GetViewUp(),
                                distance=vp.camera.GetDistance(),
                                clippingRange=vp.camera.GetClippingRange() )
        sdict['position'] = vp.pos
        sdict['size'] = vp.size
        sdict['axes'] = vp.axes
        sdict['title'] = vp.title
        sdict['xtitle'] = vp.xtitle
        sdict['ytitle'] = vp.ytitle
        sdict['ztitle'] = vp.ztitle
        sdict['backgrcol'] = colors.getColor(vp.backgrcol)
        sdict['backgrcol2'] = None
        if vp.renderer.GetGradientBackground():
            sdict['backgrcol2'] = vp.renderer.GetBackground2()
        sdict['useDepthPeeling'] = settings.useDepthPeeling
        sdict['renderLinesAsTubes'] = settings.renderLinesAsTubes
        sdict['hiddenLineRemoval'] = settings.hiddenLineRemoval
        sdict['visibleGridEdges'] = settings.visibleGridEdges
        sdict['interactorStyle'] = settings.interactorStyle
        sdict['useParallelProjection'] = settings.useParallelProjection
        sdict['defaultFont'] = settings.defaultFont
        sdict['objects'] = []

        allobjs = vp.getMeshes(includeNonPickables=True) + vp.getVolumes(includeNonPickables=True)
        acts2d = vp.renderer.GetActors2D()
        acts2d.InitTraversal()
        for i in range(acts2d.GetNumberOfItems()):
            a = acts2d.GetNextItem()
            if isinstance(a, vedo.Text2D):
                allobjs.append(a)

        allobjs = list(set(allobjs)) # make sure its unique

        for a in allobjs:
            sdict['objects'].append(toNumpy(a))

        if fr.endswith(".npz"):
            np.savez_compressed(fileoutput, vedo_scenes=[sdict])
        else:
            np.save(fileoutput, [sdict])

    ####################################################################
    # elif fr.endswith(".obj"):
    #     w = vtk.vtkOBJExporter()
    #     w.SetInputData(settings.plotter_instance.window)
    #     w.Update()
    #     colors.printc("\save Saved file:", fileoutput, c="g")


    ####################################################################
    elif fr.endswith(".x3d"):
        from vedo.docs import x3d_html
        exporter = vtk.vtkX3DExporter()
        exporter.SetBinary(binary)
        exporter.FastestOff()
        exporter.SetInput(settings.plotter_instance.window)
        exporter.SetFileName(fileoutput)
        exporter.Update()
        exporter.Write()
        x3d_html = x3d_html.replace("~fileoutput", fileoutput)
        wsize = settings.plotter_instance.window.GetSize()
        x3d_html = x3d_html.replace("~width", str(wsize[0]))
        x3d_html = x3d_html.replace("~height", str(wsize[1]))
        outF = open(fileoutput.replace('.x3d', '.html'), "w")
        outF.write(x3d_html)
        outF.close()
        colors.printc("\save Saved files:", fileoutput,
                      fileoutput.replace('.x3d', '.html'), c="g")

    ####################################################################
    elif fr.endswith(".html"):
        from vedo.backends import getNotebookBackend

        savebk = settings.notebookBackend
        settings.notebookBackend='k3d'
        plt = getNotebookBackend(settings.plotter_instance.actors, 1.5, '')

        with open(fileoutput,'w') as fp:
            fp.write(plt.get_snapshot())

        settings.notebookBackend = savebk

    else:
        colors.printc("Export extension", fr.split('.')[-1],
                      "is not supported.", c='r')
    return


def importWindow(fileinput, mtlFile=None, texturePath=None):
    """Import a whole scene from a Numpy or OBJ wavefront file.
    Return a ``Plotter`` instance.

    :param str mtlFile: MTL file for OBJ wavefront files.
    :param str texturePath: path of the texture files directory.
    """
    from vedo import Plotter

    data = None
    if isinstance(fileinput, dict):
        data = fileinput
    elif fileinput.endswith('.npy'):
        data = np.load(fileinput, allow_pickle=True, encoding="latin1").flatten()[0]
    elif fileinput.endswith('.npz'):
        data = np.load(fileinput, allow_pickle=True)['vedo_scenes'][0]

    if data is not None:
        if 'renderLinesAsTubes' in data.keys():
            settings.renderLinesAsTubes = data['renderLinesAsTubes']
        if 'hiddenLineRemoval' in data.keys():
            settings.hiddenLineRemoval = data['hiddenLineRemoval']
        if 'visibleGridEdges' in data.keys():
            settings.visibleGridEdges = data['visibleGridEdges']
        if 'interactorStyle' in data.keys():
            settings.interactorStyle = data['interactorStyle']
        if 'useParallelProjection' in data.keys():
            settings.useParallelProjection = data['useParallelProjection']
        if 'usePolygonOffset' in data.keys():
            settings.usePolygonOffset = data['usePolygonOffset']
        if 'polygonOffsetFactor' in data.keys():
            settings.polygonOffsetFactor = data['polygonOffsetFactor']
        if 'polygonOffsetUnits' in data.keys():
            settings.polygonOffsetUnits = data['polygonOffsetUnits']
        if 'interpolateScalarsBeforeMapping' in data.keys():
            settings.interpolateScalarsBeforeMapping = data['interpolateScalarsBeforeMapping']
        if 'defaultFont' in data.keys():
            settings.defaultFont = data['defaultFont']

        axes = data.pop('axes', 4)
        title = data.pop('title', '')
        backgrcol = data.pop('backgrcol', "white")
        backgrcol2 = data.pop('backgrcol2', None)
        cam = data.pop('camera', None)

        if data['shape'] != (1,1): data['size']="auto" # disable size

        vp = Plotter(size=data['size'], # not necessarily a good idea to set it
                     #shape=data['shape'], # will need to create a Renderer class first
                     axes=axes,
                     title=title,
                     bg=backgrcol,
                     bg2=backgrcol2,
        )
        vp.xtitle = data.pop('xtitle', 'x')
        vp.ytitle = data.pop('ytitle', 'y')
        vp.ztitle = data.pop('ztitle', 'z')

        if cam:
            if 'pos' in cam.keys(): vp.camera.SetPosition( cam['pos'] )
            if 'focalPoint' in cam.keys(): vp.camera.SetFocalPoint( cam['focalPoint'] )
            if 'viewup' in cam.keys(): vp.camera.SetViewUp(cam['viewup']  )
            if 'distance' in cam.keys(): vp.camera.SetDistance( cam['distance'] )
            if 'clippingRange' in cam.keys(): vp.camera.SetClippingRange( cam['clippingRange'] )
            vp.resetcam = False

        if 'objects' in data.keys():
            objs = loadNumpy(data['objects'])
            if not utils.isSequence(objs):
               objs = [objs]
        else:
            #colors.printc("Trying to import a single mesh.. use load() instead.", c='r')
            #colors.printc(" -> try to load a single object with load().", c='r')
            objs = [loadNumpy(fileinput)]

        vp.actors = objs
        return vp

    elif '.obj' in fileinput.lower():

        vp = Plotter()

        importer = vtk.vtkOBJImporter()
        importer.SetFileName(fileinput)
        if mtlFile is not False:
            if mtlFile is None:
                mtlFile = fileinput.replace('.obj', '.mtl').replace('.OBJ', '.MTL')
            importer.SetFileNameMTL(mtlFile)
        if texturePath is not False:
            if texturePath is None:
                texturePath = fileinput.replace('.obj', '.txt').replace('.OBJ', '.TXT')
            importer.SetTexturePath(texturePath)
        importer.SetRenderWindow(vp.window)
        importer.Update()

        actors = vp.renderer.GetActors()
        actors.InitTraversal()
        for i in range(actors.GetNumberOfItems()):
            vactor = actors.GetNextActor()
            act = Mesh(vactor)
            act_tu = vactor.GetTexture()
            if act_tu:
                act_tu.InterpolateOn()
                act.texture(act_tu)
            vp.actors.append( act )
        return vp


##########################################################
def screenshot(filename="screenshot.png", scale=None, returnNumpy=False):
    """
    Save a screenshot of the current rendering window.

    :param int scale: set image magnification
    :param bool returnNumpy: return a numpy array of the image
    """
    if not settings.plotter_instance or not settings.plotter_instance.window:
        colors.printc('\bomb screenshot(): Rendering window is not present, skip.', c='r')
        return settings.plotter_instance

    if filename.endswith('.pdf'):
        writer = vtk.vtkGL2PSExporter()
        writer.SetRenderWindow(settings.plotter_instance.window)
        writer.Write3DPropsAsRasterImageOff()
        writer.SilentOn()
        writer.SetSortToBSP()
        writer.SetFileFormatToPDF()
        writer.SetFilePrefix(filename.replace('.pdf',''))
        writer.Write()
        return settings.plotter_instance ##########
    elif filename.endswith('.svg'):
        writer = vtk.vtkGL2PSExporter()
        writer.SetRenderWindow(settings.plotter_instance.window)
        writer.Write3DPropsAsRasterImageOff()
        writer.SilentOn()
        writer.SetSortToBSP()
        writer.SetFileFormatToSVG()
        writer.SetFilePrefix(filename.replace('.svg',''))
        writer.Write()
        return settings.plotter_instance ##########
    elif filename.endswith('.eps'):
        writer = vtk.vtkGL2PSExporter()
        writer.SetRenderWindow(settings.plotter_instance.window)
        writer.Write3DPropsAsRasterImageOff()
        writer.SilentOn()
        writer.SetSortToBSP()
        writer.SetFileFormatToEPS()
        writer.SetFilePrefix(filename.replace('.eps',''))
        writer.Write()
        return settings.plotter_instance ##########

    if scale is None:
        scale = settings.screeshotScale

    if settings.screeshotLargeImage:
       w2if = vtk.vtkRenderLargeImage()
       w2if.SetInput(settings.plotter_instance.renderer)
       w2if.SetMagnification(scale)
    else:
        w2if = vtk.vtkWindowToImageFilter()
        w2if.SetInput(settings.plotter_instance.window)
        if hasattr(w2if, 'SetScale'):
            w2if.SetScale(scale, scale)
        if settings.screenshotTransparentBackground:
            w2if.SetInputBufferTypeToRGBA()
        w2if.ReadFrontBufferOff()  # read from the back buffer
    w2if.Update()

    if returnNumpy:
        w2ifout = w2if.GetOutput()
        npdata = utils.vtk2numpy(w2ifout.GetPointData().GetArray("ImageScalars"))
        npdata = npdata[:,[0,1,2]]
        ydim, xdim, _ = w2ifout.GetDimensions()
        npdata = npdata.reshape([xdim, ydim, -1])
        npdata = np.flip(npdata, axis=0)
        return npdata

    if filename.lower().endswith('.png'):
        writer = vtk.vtkPNGWriter()
        writer.SetFileName(filename)
        writer.SetInputData(w2if.GetOutput())
        writer.Write()
    elif filename.lower().endswith('.jpg') or filename.lower().endswith('.jpeg'):
        writer = vtk.vtkJPEGWriter()
        writer.SetFileName(filename)
        writer.SetInputData(w2if.GetOutput())
        writer.Write()
    else: #add .png
        writer = vtk.vtkPNGWriter()
        writer.SetFileName(filename+'.png')
        writer.SetInputData(w2if.GetOutput())
        writer.Write()
    return settings.plotter_instance

def ask(*question, **kwarg):
    """
    Ask a question from command line. Return the answer as a string.
    See function `printc()` for the description of the options.
    """
    kwarg.update({'end': ' '})
    if 'invert' not in kwarg.keys():
        kwarg.update({'invert': True})
    if 'box' in kwarg.keys():
        kwarg.update({'box': ''})
    colors.printc(*question, **kwarg)
    resp = input()
    return resp

class Video:
    """
    Class to generate a video from the specified rendering window.
    Program ``ffmpeg`` is used to create video from each generated frame.
    :param str name: name of the output file.
    :param int fps: set the number of frames per second.
    :param float duration: set the total `duration` of the video and recalculates `fps` accordingly.
    :param str ffmpeg: set path to ffmpeg program. Default value assumes ffmpeg command is in the path.

    |makeVideo| |makeVideo.py|_
    """

    def __init__(self,
                 name="movie.mp4",
                 duration=None,
                 fps=24,
                 backend='ffmpeg',
                ):

        from tempfile import TemporaryDirectory

        self.name = name
        self.duration = duration
        self.backend = backend
        self.fps = float(fps)
        self.command = "ffmpeg -loglevel panic -y -r"
        self.options = "-b:v 8000k"

        self.frames = []
        self.tmp_dir = TemporaryDirectory()
        self.get_filename = lambda x: os.path.join(self.tmp_dir.name, x)
        colors.printc("\video Video", self.name, "is open...", c="m")

    def addFrame(self):
        """Add frame to current video."""
        fr = self.get_filename(str(len(self.frames)) + ".png")
        screenshot(fr)
        self.frames.append(fr)
        return self

    def pause(self, pause=0):
        """Insert a `pause`, in seconds."""
        fr = self.frames[-1]
        n = int(self.fps * pause)
        for _ in range(n):
            fr2 = self.get_filename(str(len(self.frames)) + ".png")
            self.frames.append(fr2)
            os.system("cp -f %s %s" % (fr, fr2))
        return self


    def action(self, elevation_range=(0,80),
               azimuth_range=(0,359),
               zoom=None,
               cam1=None, cam2=None,
               resetcam=False,
               ):
        """
        Automatic shooting of a static scene by specifying rotation and elevation ranges.

        :param list elevation_range: initial and final elevation angles
        :param list azimuth_range: initial and final azimuth angles
        :param float zoom: initial zooming
        :param cam1 cam2: initial and final camera position, can be dictionary or a vtkCamera
        """
        if not self.duration:
            self.duration = 5

        def buildcam(cm):
            cm_pos = cm.pop("pos", None)
            cm_focalPoint = cm.pop("focalPoint", None)
            cm_viewup = cm.pop("viewup", None)
            cm_distance = cm.pop("distance", None)
            cm_clippingRange = cm.pop("clippingRange", None)
            cm_parallelScale = cm.pop("parallelScale", None)
            cm_thickness = cm.pop("thickness", None)
            cm_viewAngle = cm.pop("viewAngle", None)
            cm = vtk.vtkCamera()
            if cm_pos is not None: cm.SetPosition(cm_pos)
            if cm_focalPoint is not None: cm.SetFocalPoint(cm_focalPoint)
            if cm_viewup is not None: cm.SetViewUp(cm_viewup)
            if cm_distance is not None: cm.SetDistance(cm_distance)
            if cm_clippingRange is not None: cm.SetClippingRange(cm_clippingRange)
            if cm_parallelScale is not None: cm.SetParallelScale(cm_parallelScale)
            if cm_thickness is not None: cm.SetThickness(cm_thickness)
            if cm_viewAngle is not None: cm.SetViewAngle(cm_viewAngle)
            return cm

        vp = settings.plotter_instance

        if zoom:
            vp.camera.Zoom(zoom)

        if isinstance(cam1, dict):
            cam1 = buildcam(cam1)
        if isinstance(cam2, dict):
            cam2 = buildcam(cam2)

        if len(elevation_range)==2:
            vp.camera.Elevation(elevation_range[0])
        if len(azimuth_range)==2:
            vp.camera.Azimuth(azimuth_range[0])

        vp.show(resetcam=resetcam, interactive=False)
        # if resetcam: vp.renderer.ResetCamera()

        n = self.fps * self.duration
        for i in range(int(n)):
            if cam1 and cam2:
                vp.moveCamera(cam1, cam2, i/n)
            else:
                if len(elevation_range)==2:
                    vp.camera.Elevation((elevation_range[1]-elevation_range[0])/n)
                if len(azimuth_range)==2:
                    vp.camera.Azimuth((azimuth_range[1]-azimuth_range[0])/n)
            vp.show()
            self.addFrame()
        return self

    def close(self):
        """
        Render the video and write to file.
        Return the current Plotter instance.
        """
        if self.duration:
            self.fps = len(self.frames) / float(self.duration)
            colors.printc("Recalculated video FPS to", round(self.fps, 3), c="m")
        else:
            self.fps = int(self.fps)

        self.name = self.name.split('.')[0]+'.mp4'

        ########################################
        if self.backend == 'ffmpeg':
            out = os.system(self.command + " " + str(self.fps)
                            + " -i " + self.tmp_dir.name + os.sep
                            + "%01d.png " + self.options + " " + self.name)
            if out:
                colors.printc("ffmpeg returning error", c='r')
            else:
                colors.printc("\save Video saved as", self.name, c="m")

        ########################################
        elif 'cv' in self.backend:
            try:
                import cv2
            except:
                colors.printc("Error in Video backend: opencv not installed!", c='r')
                return

            cap = cv2.VideoCapture(os.path.join(self.tmp_dir.name, "%1d.png"))
            fourcc = cv2.VideoWriter_fourcc(*"mp4v")
            w,h = settings.plotter_instance.window.GetSize()
            writer = cv2.VideoWriter(self.name, fourcc, self.fps, (w, h), True)

            found = False
            while True:
                ret, frame = cap.read()
                if not ret: break
                writer.write(frame)
                found = True

            cap.release()
            writer.release()
            if found:
                colors.printc("\save Video saved as", self.name, c="m")
            else:
                colors.printc("could not find snapshots", c='r')

        self.tmp_dir.cleanup()
        return settings.plotter_instance


