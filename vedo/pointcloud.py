import numpy as np
import vtk, os
import vedo
import vedo.colors as colors
import vedo.docs as docs
import vedo.settings as settings
import vedo.utils as utils
from vedo.base import BaseActor


__doc__ = ("""Submodule to manage point clouds."""
    + docs._defs
)

__all__ = ["Points",
           "Point",
           "cluster",
           "removeOutliers",
           "connectedPoints",
           "smoothMLS3D",
           "pointCloudFrom",
           "visiblePoints",
           "delaunay2D",
           "fitLine",
           "fitCircle",
           "fitPlane",
           "fitSphere",
           "pcaEllipsoid",
           "recoSurface",
           ]


###################################################

def cluster(points, radius):
    """
    Clustering of points in space.

    `radius` is the radius of local search.
    Individual subsets can be accessed through ``mesh.clusters``.

    |clustering| |clustering.py|_
    """
    if isinstance(points, vtk.vtkActor):
        poly = points.GetMapper().GetInput()
    else:
        src = vtk.vtkPointSource()
        src.SetNumberOfPoints(len(points))
        src.Update()
        vpts = src.GetOutput().GetPoints()
        for i, p in enumerate(points):
            vpts.SetPoint(i, p)
        poly = src.GetOutput()

    cluster = vtk.vtkEuclideanClusterExtraction()
    cluster.SetInputData(poly)
    cluster.SetExtractionModeToAllClusters()
    cluster.SetRadius(radius)
    cluster.ColorClustersOn()
    cluster.Update()

    idsarr = cluster.GetOutput().GetPointData().GetArray("ClusterId")
    Nc = cluster.GetNumberOfExtractedClusters()

    sets = [[] for i in range(Nc)]
    for i, p in enumerate(points):
        sets[idsarr.GetValue(i)].append(p)

    acts = []
    for i, aset in enumerate(sets):
        acts.append(Points(aset, c=i))

    asse = vedo.assembly.Assembly(acts)

    asse.info["clusters"] = sets
    print("Nr. of extracted clusters", Nc)
    if Nc > 10:
        print("First ten:")
    for i in range(Nc):
        if i > 9:
            print("...")
            break
        print("Cluster #" + str(i) + ",  N =", len(sets[i]))
    print("Access individual clusters through attribute: obj.info['cluster']")
    return asse


def removeOutliers(points, radius, neighbors=5):
    """
    Remove outliers from a cloud of points within the specified `radius` search.

    |clustering| |clustering.py|_
    """
    isactor = False
    if isinstance(points, vtk.vtkActor):
        isactor = True
        poly = points.GetMapper().GetInput()
    else:
        src = vtk.vtkPointSource()
        src.SetNumberOfPoints(len(points))
        src.Update()
        vpts = src.GetOutput().GetPoints()
        for i, p in enumerate(points):
            vpts.SetPoint(i, p)
        poly = src.GetOutput()

    removal = vtk.vtkRadiusOutlierRemoval()
    removal.SetInputData(poly)
    removal.SetRadius(radius)
    removal.SetNumberOfNeighbors(neighbors)
    removal.GenerateOutliersOff()
    removal.Update()
    rpoly = removal.GetOutput()
    outpts = []
    for i in range(rpoly.GetNumberOfPoints()):
        outpts.append(list(rpoly.GetPoint(i)))
    outpts = np.array(outpts)
    if not isactor:
        return outpts

    return Points(outpts)



def smoothMLS3D(meshs, neighbours=10):
    """
    A time sequence of point clouds (Mesh) is being smoothed in 4D (3D + time)
    using a `MLS (Moving Least Squares)` algorithm variant.
    The time associated to an mesh must be specified in advance with ``mesh.time()`` method.
    Data itself can suggest a meaningful time separation based on the spatial
    distribution of points.

    :param int neighbours: fixed nr. of neighbours in space-time to take into account in the fit.

    |moving_least_squares3D| |moving_least_squares3D.py|_
    """
    from scipy.spatial import KDTree

    coords4d = []
    for a in meshs:  # build the list of 4d coordinates
        coords3d = a.points()
        n = len(coords3d)
        pttimes = [[a.time()]] * n
        coords4d += np.append(coords3d, pttimes, axis=1).tolist()

    avedt = float(meshs[-1].time() - meshs[0].time()) / len(meshs)
    print("Average time separation between meshes dt =", round(avedt, 3))

    coords4d = np.array(coords4d)
    newcoords4d = []
    kd = KDTree(coords4d, leafsize=neighbours)
    suggest = ""

    pb = utils.ProgressBar(0, len(coords4d))
    for i in pb.range():
        mypt = coords4d[i]

        # dr = np.sqrt(3*dx**2+dt**2)
        # iclosest = kd.query_ball_Point(mypt, r=dr)
        # dists, iclosest = kd.query(mypt, k=None, distance_upper_bound=dr)
        dists, iclosest = kd.query(mypt, k=neighbours)
        closest = coords4d[iclosest]

        nc = len(closest)
        if nc >= neighbours and nc > 5:
            m = np.linalg.lstsq(closest, [1.0] * nc)[0]  # needs python3
            vers = m / np.linalg.norm(m)
            hpcenter = np.mean(closest, axis=0)  # hyperplane center
            dist = np.dot(mypt - hpcenter, vers)
            projpt = mypt - dist * vers
            newcoords4d.append(projpt)

            if not i % 1000:  # work out some stats
                v = np.std(closest, axis=0)
                vx = round((v[0] + v[1] + v[2]) / 3, 3)
                suggest = "data suggest dt=" + str(vx)

        pb.print(suggest)
    newcoords4d = np.array(newcoords4d)

    ctimes = newcoords4d[:, 3]
    ccoords3d = np.delete(newcoords4d, 3, axis=1)  # get rid of time
    act = Points(ccoords3d)
    act.cmap('jet', ctimes)  # use a colormap to associate a color to time
    return act


def connectedPoints(mesh, radius, mode=0, regions=(), vrange=(0,1), seeds=(), angle=0):
    """
    Extracts and/or segments points from a point cloud based on geometric distance measures
    (e.g., proximity, normal alignments, etc.) and optional measures such as scalar range.
    The default operation is to segment the points into "connected" regions where the connection
    is determined by an appropriate distance measure. Each region is given a region id.

    Optionally, the filter can output the largest connected region of points; a particular region
    (via id specification); those regions that are seeded using a list of input point ids;
    or the region of points closest to a specified position.

    The key parameter of this filter is the radius defining a sphere around each point which defines
    a local neighborhood: any other points in the local neighborhood are assumed connected to the point.
    Note that the radius is defined in absolute terms.

    Other parameters are used to further qualify what it means to be a neighboring point.
    For example, scalar range and/or point normals can be used to further constrain the neighborhood.
    Also the extraction mode defines how the filter operates.
    By default, all regions are extracted but it is possible to extract particular regions;
    the region closest to a seed point; seeded regions; or the largest region found while processing.
    By default, all regions are extracted.

    On output, all points are labeled with a region number.
    However note that the number of input and output points may not be the same:
    if not extracting all regions then the output size may be less than the input size.

    :param float radius: radius variable specifying a local sphere used to define local point neighborhood

    :param int mode:

        - 0,  Extract all regions
        - 1,  Extract point seeded regions
        - 2,  Extract largest region
        - 3,  Test specified regions
        - 4,  Extract all regions with scalar connectivity
        - 5,  Extract point seeded regions

    :param list regions: a list of non-negative regions id to extract

    :param list vrange: scalar range to use to extract points based on scalar connectivity

    :param list seeds: a list of non-negative point seed ids

    :param list angle: points are connected if the angle between their normals is
        within this angle threshold (expressed in degrees).
    """
    # https://vtk.org/doc/nightly/html/classvtkConnectedPointsFilter.html
    cpf = vtk.vtkConnectedPointsFilter()
    cpf.SetInputData(mesh.polydata())
    cpf.SetRadius(radius)
    if   mode == 0: # Extract all regions
        pass

    elif mode == 1: # Extract point seeded regions
        cpf.SetExtractionModeToPointSeededRegions()
        for s in seeds:
            cpf.AddSeed(s)

    elif mode == 2: # Test largest region
        cpf.SetExtractionModeToLargestRegion()

    elif mode == 3: # Test specified regions
        cpf.SetExtractionModeToSpecifiedRegions()
        for r in regions:
            cpf.AddSpecifiedRegion(r)

    elif mode == 4: # Extract all regions with scalar connectivity
        cpf.SetExtractionModeToLargestRegion()
        cpf.ScalarConnectivityOn()
        cpf.SetScalarRange(vrange[0], vrange[1])

    elif mode == 5: # Extract point seeded regions
        cpf.SetExtractionModeToLargestRegion()
        cpf.ScalarConnectivityOn()
        cpf.SetScalarRange(vrange[0], vrange[1])
        cpf.AlignedNormalsOn()
        cpf.SetNormalAngle(angle)

    cpf.Update()
    m = Points(cpf.GetOutput())
    m.name = "connectedPoints"
    return m


def pointCloudFrom(obj, interpolateCellData=False):
    """Build a `Mesh` object (as a point cloud) from any VTK dataset.

    :param bool interpolateCellData: if True cell data is interpolated at point positions.
    """
    from vtk.numpy_interface import dataset_adapter
    if interpolateCellData:
        c2p = vtk.vtkCellDataToPointData()
        c2p.SetInputData(obj)
        c2p.Update()
        obj = c2p.GetOutput()

    wrapped = dataset_adapter.WrapDataObject(obj)
    ptdatanames = wrapped.PointData.keys()

    vpts = obj.GetPoints()
    poly = vtk.vtkPolyData()
    poly.SetPoints(vpts)

    for name in ptdatanames:
        arr = obj.GetPointData().GetArray(name)
        poly.GetPointData().AddArray(arr)

    m = Points(poly, c=None)
    m.name = "pointCloud"
    return m


def visiblePoints(mesh, area=(), tol=None, invert=False):
    """Extract points based on whether they are visible or not.
    Visibility is determined by accessing the z-buffer of a rendering window.
    The position of each input point is converted into display coordinates,
    and then the z-value at that point is obtained.
    If within the user-specified tolerance, the point is considered visible.
    Associated data attributes are passed to the output as well.

    This filter also allows you to specify a rectangular window in display (pixel)
    coordinates in which the visible points must lie.

    :param list area: specify a rectangular region as (xmin,xmax,ymin,ymax)

    :param float tol: a tolerance in normalized display coordinate system

    :param bool invert: select invisible points instead.

    :Example:
        .. code-block:: python

            from vedo import Ellipsoid, show, visiblePoints

            s = Ellipsoid().rotateY(30)

            #Camera options: pos, focalPoint, viewup, distance,
            # clippingRange, parallelScale, thickness, viewAngle
            camopts = dict(pos=(0,0,25), focalPoint=(0,0,0))
            show(s, camera=camopts, offscreen=True)

            m = visiblePoints(s)
            #print('visible pts:', m.points()) # numpy array
            show(m, new=True, axes=1) # optionally draw result on a new window
    """
    # specify a rectangular region
    svp = vtk.vtkSelectVisiblePoints()
    svp.SetInputData(mesh.polydata())
    svp.SetRenderer(settings.plotter_instance.renderer)

    if len(area)==4:
        svp.SetSelection(area[0],area[1],area[2],area[3])
    if tol is not None:
        svp.SetTolerance(tol)
    if invert:
        svp.SelectInvisibleOn()
    svp.Update()

    m = Points(svp.GetOutput()).pointSize(5)
    m.name = "VisiblePoints"
    return m


def delaunay2D(plist, mode='scipy', boundaries=(), tol=None, alpha=0, offset=0, transform=None):
    """
    Create a mesh from points in the XY plane.
    If `mode='fit'` then the filter computes a best fitting
    plane and projects the points onto it.
    If `mode='fit'` then the xy plane is assumed.

    When mode=='fit' or 'xy'

    :param float tol: specify a tolerance to control discarding of closely spaced points.
        This tolerance is specified as a fraction of the diagonal length of the bounding box of the points.

    :param float alpha: for a non-zero alpha value, only edges or triangles contained
        within a sphere centered at mesh vertices will be output.
        Otherwise, only triangles will be output.

    :param float offset: multiplier to control the size of the initial, bounding Delaunay triangulation.
    :param transform: a vtk transformation (eg. a thinplate spline)
        which is applied to points to generate a 2D problem.
        This maps a 3D dataset into a 2D dataset where triangulation can be done on the XY plane.
        The points are transformed and triangulated.
        The topology of triangulated points is used as the output topology.

    |delaunay2d| |delaunay2d.py|_
    """
    if isinstance(plist, Points):
        plist = plist.points()
    else:
        plist = np.ascontiguousarray(plist)
        if plist.shape[1] == 2: # make it 3d
            plist = np.c_[plist, np.zeros(len(plist))]

    if mode == 'scipy':
        from scipy.spatial import Delaunay as scipy_Delaunay
        tri = scipy_Delaunay(plist[:, 0:2])
        return vedo.mesh.Mesh([plist, tri.simplices])
        #############################################

    pd = vtk.vtkPolyData()
    vpts = vtk.vtkPoints()
    vpts.SetData(utils.numpy2vtk(plist, dtype=np.float))
    pd.SetPoints(vpts)

    delny = vtk.vtkDelaunay2D()
    delny.SetInputData(pd)
    if tol:
        delny.SetTolerance(tol)
    delny.SetAlpha(alpha)
    delny.SetOffset(offset)
    if transform:
        if hasattr(transform, "transform"):
            transform = transform.transform
        delny.SetTransform(transform)

    if mode=='xy' and len(boundaries):
        boundary = vtk.vtkPolyData()
        boundary.SetPoints(vpts)
        aCellArray = vtk.vtkCellArray()
        for b in boundaries:
            cPolygon = vtk.vtkPolygon()
            for idd in b:
                cPolygon.GetPointIds().InsertNextId(idd)
            aCellArray.InsertNextCell(cPolygon)
        boundary.SetPolys(aCellArray)
        delny.SetSourceData(boundary)

    if mode=='fit':
        delny.SetProjectionPlaneMode(vtk.VTK_BEST_FITTING_PLANE)
    delny.Update()
    return vedo.mesh.Mesh(delny.GetOutput()).clean().lighting('off')


def _rotatePoints(points, n0=None, n1=(0,0,1)):
    """
    Rotate a set of 3D points from direction n0 to direction n1.

    Return the rotated points and the normal to the fitting plane (if n0 is None).
    The pointing direction of the normal in this case is arbitrary.
    """
    points = np.asarray(points)

    if points.ndim == 1:
        points = points[np.newaxis,:]

    if len(points[0])==2:
        return points, (0,0,1)

    if n0 is None: # fit plane
        datamean = points.mean(axis=0)
        vv = np.linalg.svd(points - datamean)[2]
        n0 = np.cross(vv[0], vv[1])

    n0 = n0/np.linalg.norm(n0)
    n1 = n1/np.linalg.norm(n1)
    k = np.cross(n0, n1)
    l = np.linalg.norm(k)
    if not l:
        k = n0
    k /= np.linalg.norm(k)

    ct = np.dot(n0, n1)
    theta = np.arccos(ct)
    st = np.sin(theta)
    v = k * (1-ct)

    rpoints = []
    for p in points:
        a = p * ct
        b = np.cross(k,p) * st
        c = v * np.dot(k,p)
        rpoints.append(a + b + c)

    return np.array(rpoints), n0


def fitLine(points):
    """
    Fits a line through points.

    Extra info is stored in ``Line.slope``, ``Line.center``, ``Line.variances``.

    |fitline| |fitline.py|_
    """
    if isinstance(points, Points):
        points = points.points()
    data = np.array(points)
    datamean = data.mean(axis=0)
    uu, dd, vv = np.linalg.svd(data - datamean)
    vv = vv[0] / np.linalg.norm(vv[0])
    # vv contains the first principal component, i.e. the direction
    # vector of the best fit line in the least squares sense.
    xyz_min = points.min(axis=0)
    xyz_max = points.max(axis=0)
    a = np.linalg.norm(xyz_min - datamean)
    b = np.linalg.norm(xyz_max - datamean)
    p1 = datamean - a * vv
    p2 = datamean + b * vv
    l = vedo.shapes.Line(p1, p2, lw=1)
    l.slope = vv
    l.center = datamean
    l.variances = dd
    return l


def fitPlane(points, signed=False):
    """
    Fits a plane to a set of points.

    Extra info is stored in ``Plane.normal``, ``Plane.center``, ``Plane.variance``.

    :param bool signed: if True flip sign of the normal based on the ordering of the points

    .. hint:: Example: |fitplanes.py|_
    """
    if isinstance(points, Points):
        points = points.points()
    data = np.array(points)
    datamean = data.mean(axis=0)
    pts = data - datamean
    res = np.linalg.svd(pts)
    dd, vv = res[1], res[2]
    n = np.cross(vv[0], vv[1])
    if signed:
        v = np.zeros_like(pts)
        for i in range(len(pts)-1):
            vi = np.cross(pts[i],  pts[i+1])
            v[i] = vi/np.linalg.norm(vi)
        ns = np.mean(v, axis=0) # normal to the points plane
        if np.dot(n,ns) < 0:
            n = -n
    xyz_min = points.min(axis=0)
    xyz_max = points.max(axis=0)
    s = np.linalg.norm(xyz_max - xyz_min)
    pla = vedo.shapes.Plane(datamean, n, s, s)
    pla.normal = n
    pla.center = datamean
    pla.variance = dd[2]
    pla.name = "fitPlane"
    return pla


def fitCircle(points):
    """
    Fits a circle through a set of 3D points, with a very fast non-iterative method.

    Returns the center, radius, normal_to_circle.

    Reference: J.F. Crawford, Nucl. Instr. Meth. 211, 1983, 223-225.
    """
    if len(points) == 2:
        data = np.c_[points[0], points[1]]
    else:
        data = np.asarray(points)

    offs = data.mean(axis=0)
    data, n0 = _rotatePoints(data-offs)

    xi = data[:,0]
    yi = data[:,1]

    x   = sum(xi)
    xi2 = xi*xi
    xx  = sum(xi2)
    xxx = sum(xi2*xi)

    y   = sum(yi)
    yi2 = yi*yi
    yy  = sum(yi2)
    yyy = sum(yi2*yi)

    xiyi = xi*yi
    xy  = sum(xiyi)
    xyy = sum(xiyi*yi)
    xxy = sum(xi*xiyi)

    N = len(xi)
    k = (xx+yy)/N

    a1 = xx-x*x/N
    b1 = xy-x*y/N
    c1 = 0.5*(xxx + xyy - x*k)

    a2 = xy-x*y/N
    b2 = yy-y*y/N
    c2 = 0.5*(xxy + yyy - y*k)

    d = a2*b1 - a1*b2
    if not d:
        return offs, 0, n0
    x0 = (b1*c2 - b2*c1)/d
    y0 = (c1 - a1*x0)/b1

    R = np.sqrt(x0*x0 + y0*y0 -1/N*(2*x0*x +2*y0*y -xx -yy))

    c, _ = _rotatePoints([x0,y0,0], (0,0,1), n0)

    return c[0]+offs, R, n0


def fitSphere(coords):
    """
    Fits a sphere to a set of points.

    Extra info is stored in ``Sphere.radius``, ``Sphere.center``, ``Sphere.residue``.

    .. hint:: Example: |fitspheres1.py|_

        |fitspheres2| |fitspheres2.py|_
    """
    if isinstance(coords, Points):
        coords = coords.points()
    coords = np.array(coords)
    n = len(coords)
    A = np.zeros((n, 4))
    A[:, :-1] = coords * 2
    A[:, 3] = 1
    f = np.zeros((n, 1))
    x = coords[:, 0]
    y = coords[:, 1]
    z = coords[:, 2]
    f[:, 0] = x * x + y * y + z * z
    C, residue, rank, sv = np.linalg.lstsq(A, f)  # solve AC=f
    if rank < 4:
        return None
    t = (C[0] * C[0]) + (C[1] * C[1]) + (C[2] * C[2]) + C[3]
    radius = np.sqrt(t)[0]
    center = np.array([C[0][0], C[1][0], C[2][0]])
    if len(residue):
        residue = np.sqrt(residue[0]) / n
    else:
        residue = 0
    s = vedo.shapes.Sphere(center, radius, c=(1,0,0)).wireframe(1)
    s.radius = radius # used by fitSphere
    s.center = center
    s.residue = residue
    s.name = "fitSphere"
    return s


def pcaEllipsoid(points, pvalue=0.95):
    """
    Show the oriented PCA ellipsoid that contains fraction `pvalue` of points.

    :param float pvalue: ellypsoid will contain the specified fraction of points.

    Extra can be calculated with ``mesh.asphericity()``, ``mesh.asphericity_error()``
    (asphericity is equal to 0 for a perfect sphere).

    Axes can be accessed in ``mesh.va``, ``mesh.vb``, ``mesh.vc``.
    End point of the axes are stored in ``mesh.axis1``, ``mesh.axis12`` and ``mesh.axis3``.

    .. hint:: Examples: |pca.py|_  |cell_colony.py|_

         |pca| |cell_colony|
    """
    from scipy.stats import f

    if isinstance(points, Points):
        coords = points.points()
    else:
        coords = points
    if len(coords) < 4:
        colors.printc("Warning in fitEllipsoid(): not enough points!", c='y')
        return None

    P = np.array(coords, ndmin=2, dtype=float)
    cov = np.cov(P, rowvar=0)     # covariance matrix
    U, s, R = np.linalg.svd(cov)  # singular value decomposition
    p, n = s.size, P.shape[0]
    fppf = f.ppf(pvalue, p, n-p)*(n-1)*p*(n+1)/n/(n-p)  # f % point function
    cfac = 1 + 6/(n-1)            # correction factor for low statistics
    ua, ub, uc = np.sqrt(s*fppf)/cfac  # semi-axes (largest first)
    center = np.mean(P, axis=0)   # centroid of the hyperellipsoid

    elli = vedo.shapes.Ellipsoid((0,0,0), (1,0,0), (0,1,0), (0,0,1), alpha=0.2)

    matri = vtk.vtkMatrix4x4()
    matri.DeepCopy((R[0][0] * ua*2, R[1][0] * ub*2, R[2][0] * uc*2, center[0],
                    R[0][1] * ua*2, R[1][1] * ub*2, R[2][1] * uc*2, center[1],
                    R[0][2] * ua*2, R[1][2] * ub*2, R[2][2] * uc*2, center[2],
                    0, 0, 0, 1))
    vtra = vtk.vtkTransform()
    vtra.SetMatrix(matri)
    # assign the transformation
    elli.SetScale(vtra.GetScale())
    elli.SetOrientation(vtra.GetOrientation())
    elli.SetPosition(vtra.GetPosition())

    elli.GetProperty().BackfaceCullingOn()

    elli.nr_of_points = n
    elli.va = ua
    elli.vb = ub
    elli.vc = uc
    elli.axis1 = vtra.TransformPoint([1,0,0])
    elli.axis2 = vtra.TransformPoint([0,1,0])
    elli.axis3 = vtra.TransformPoint([0,0,1])
    elli.transformation = vtra
    elli.name = "fitEllipsoid"
    return elli


def recoSurface(pts, dims=(100,100,100), radius=None,
                sampleSize=None, holeFilling=True, bounds=(), pad=0.1):
    """
    Surface reconstruction from a scattered cloud of points.

    :param int dims: number of voxels in x, y and z to control precision.

    :param float radius: radius of influence of each point.
        Smaller values generally improve performance markedly.
        Note that after the signed distance function is computed,
        any voxel taking on the value >= radius
        is presumed to be "unseen" or uninitialized.

    :param int sampleSize: if normals are not present
        they will be calculated using this sample size per point.

    :param bool holeFilling: enables hole filling, this generates
        separating surfaces between the empty and unseen portions of the volume.

    :param list bounds: region in space in which to perform the sampling
        in format (xmin,xmax, ymin,ymax, zim, zmax)

    :param float pad: increase by this fraction the bounding box

    |recosurface| |recosurface.py|_
    """
    if not utils.isSequence(dims):
        dims = (dims,dims,dims)

    if isinstance(pts, Points):
        polyData = pts.polydata()
    else:
        polyData = vedo.pointcloud.Points(pts).polydata()

    sdf = vtk.vtkSignedDistance()

    if len(bounds)==6:
        sdf.SetBounds(bounds)
    else:
        x0, x1, y0, y1, z0, z1 = polyData.GetBounds()
        sdf.SetBounds(x0-(x1-x0)*pad, x1+(x1-x0)*pad,
                      y0-(y1-y0)*pad, y1+(y1-y0)*pad,
                      z0-(z1-z0)*pad, z1+(z1-z0)*pad)

    if polyData.GetPointData().GetNormals():
        sdf.SetInputData(polyData)
    else:
        normals = vtk.vtkPCANormalEstimation()
        normals.SetInputData(polyData)
        if not sampleSize:
            sampleSize = int(polyData.GetNumberOfPoints()/50)
        normals.SetSampleSize(sampleSize)
        normals.SetNormalOrientationToGraphTraversal()
        sdf.SetInputConnection(normals.GetOutputPort())
        #print("Recalculating normals with sample size =", sampleSize)

    if radius is None:
        b = polyData.GetBounds()
        diagsize = np.sqrt((b[1]-b[0])**2 + (b[3]-b[2])**2 + (b[5]-b[4])**2)
        radius = diagsize / (sum(dims)/3) * 5
        #print("Calculating mesh from points with radius =", radius)

    sdf.SetRadius(radius)
    sdf.SetDimensions(dims)
    sdf.Update()

    surface = vtk.vtkExtractSurface()
    surface.SetRadius(radius * 0.99)
    surface.SetHoleFilling(holeFilling)
    surface.ComputeNormalsOff()
    surface.ComputeGradientsOff()
    surface.SetInputConnection(sdf.GetOutputPort())
    surface.Update()
    return vedo.mesh.Mesh(surface.GetOutput())



###################################################
def Point(pos=(0, 0, 0), r=12, c="red", alpha=1):
    """Create a simple point."""
    if isinstance(pos, vtk.vtkActor):
        pos = pos.GetPosition()
    pd = utils.buildPolyData([[0,0,0]])
    if len(pos)==2:
        pos = (pos[0], pos[1], 0.)
    pt = Points(pd, c, alpha, r)
    pt.SetPosition(pos)
    pt.name = "Point"
    return pt

###################################################
class Points(vtk.vtkFollower, BaseActor):
    """
    Build a ``Mesh`` made of only vertex points for a list of 2D/3D points.
    Both shapes (N, 3) or (3, N) are accepted as input, if N>3.
    For very large point clouds a list of colors and alpha can be assigned to each
    point in the form `c=[(R,G,B,A), ... ]` where `0 <= R < 256, ... 0 <= A < 256`.

    :param float r: point radius.
    :param c: color name, number, or list of [R,G,B] colors of same length as plist.
    :type c: int, str, list
    :param float alpha: transparency in range [0,1].

    Example:
        .. code-block:: python

            import numpy as np
            from vedo import *

            def fibonacci_sphere(n):
                s = np.linspace(0, n, num=n, endpoint=False)
                theta = s * 2.399963229728653
                y = 1 - s * (2/(n-1))
                r = np.sqrt(1 - y * y)
                x = np.cos(theta) * r
                z = np.sin(theta) * r
                return [x,y,z]

            Points(fibonacci_sphere(1000)).show(axes=1)


    |manypoints.py|_ |lorenz.py|_
    |lorenz|
    """
    def __init__(
        self,
        inputobj=None,
        c=(0.2,0.2,0.2),
        alpha=1,
        r=4,
    ):
        vtk.vtkActor.__init__(self)
        BaseActor.__init__(self)

        self._data = None
        self.point_locator = None
        self.cell_locator = None

        self._mapper = vtk.vtkPolyDataMapper()
        self.SetMapper(self._mapper)

        self._scals_idx = 0  # index of the active scalar changed from CLI
        self._ligthingnr = 0 # index of the lighting mode changed from CLI

        self.property = self.GetProperty()
        try:
            self.property.RenderPointsAsSpheresOn()
        except:
            pass

        if inputobj is None:####################
            self._data = vtk.vtkPolyData()
            return
        ########################################

        self.property.SetRepresentationToPoints()
        self.property.SetPointSize(r)
        self.lighting(ambient=0.7, diffuse=0.3)

        if isinstance(inputobj, vtk.vtkActor):
            polyCopy = vtk.vtkPolyData()
            pr = vtk.vtkProperty()
            pr.DeepCopy(inputobj.GetProperty())
            polyCopy.DeepCopy(inputobj.GetMapper().GetInput())
            pr.SetRepresentationToPoints()
            pr.SetPointSize(r)
            self._data = polyCopy
            self._mapper.SetInputData(polyCopy)
            self._mapper.SetScalarVisibility(inputobj.GetMapper().GetScalarVisibility())
            self.SetProperty(pr)

        elif isinstance(inputobj, vtk.vtkPolyData):
            if inputobj.GetNumberOfCells() == 0:
                carr = vtk.vtkCellArray()
                for i in range(inputobj.GetNumberOfPoints()):
                    carr.InsertNextCell(1)
                    carr.InsertCellPoint(i)
                inputobj.SetVerts(carr)
            self._data = inputobj  # cache vtkPolyData and mapper for speed

        elif utils.isSequence(inputobj): # passing point coords
            plist = inputobj
            n = len(plist)

            if n == 3:  # assume plist is in the format [all_x, all_y, all_z]
                if utils.isSequence(plist[0]) and len(plist[0]) > 3:
                    plist = np.stack((plist[0], plist[1], plist[2]), axis=1)
            elif n == 2:  # assume plist is in the format [all_x, all_y, 0]
                if utils.isSequence(plist[0]) and len(plist[0]) > 3:
                    plist = np.stack((plist[0], plist[1], np.zeros(len(plist[0]))), axis=1)

            if n and len(plist[0]) == 2: # make it 3d
                plist = np.c_[np.array(plist), np.zeros(len(plist))]

            if ((utils.isSequence(c)
                 and (len(c)>3
                      or (utils.isSequence(c[0]) and len(c[0])==4)
                     )
                )
                or utils.isSequence(alpha) ):

                cols = c

                n = len(plist)
                if n != len(cols):
                    colors.printc("Mismatch in Points() colors", n, len(cols), c='r')
                    raise RuntimeError()

                src = vtk.vtkPointSource()
                src.SetNumberOfPoints(n)
                src.Update()

                vgf = vtk.vtkVertexGlyphFilter()
                vgf.SetInputData(src.GetOutput())
                vgf.Update()
                pd = vgf.GetOutput()

                pd.GetPoints().SetData(utils.numpy2vtk(plist, dtype=np.float))

                ucols = vtk.vtkUnsignedCharArray()
                ucols.SetNumberOfComponents(4)
                ucols.SetName("Points_RGBA")
                if utils.isSequence(alpha):
                    if len(alpha) != n:
                        colors.printc("Mismatch in Points() alphas", n, len(alpha), c='r')
                        raise RuntimeError()
                    alphas = alpha
                    alpha = 1
                else:
                   alphas = (alpha,) * n

                if utils.isSequence(cols):
                    c = None
                    if len(cols[0]) == 4:
                        for i in range(n): # FAST
                            rc,gc,bc,ac = cols[i]
                            ucols.InsertNextTuple4(rc, gc, bc, ac)
                    else:
                        for i in range(n): # SLOW
                            rc,gc,bc = colors.getColor(cols[i])
                            ucols.InsertNextTuple4(rc*255, gc*255, bc*255, alphas[i]*255)
                else:
                    c = cols

                pd.GetPointData().SetScalars(ucols)
                self._mapper.SetInputData(pd)
                self._mapper.ScalarVisibilityOn()
                self._data = pd

            else:

                pd = utils.buildPolyData(plist)
                self._mapper.SetInputData(pd)
                c = colors.getColor(c)
                self.property.SetColor(c)
                self.property.SetOpacity(alpha)
                self._data = pd

            return
            ##########

        elif isinstance(inputobj, str):
            verts = vedo.io.load(inputobj)
            self.filename = inputobj
            self._data = verts.polydata()

        else:
            colors.printc("Error: cannot build Points from type:\n", [inputobj], c='r')
            raise RuntimeError()

        c = colors.getColor(c)
        self.property.SetColor(c)
        self.property.SetOpacity(alpha)

        self._mapper.SetInputData(self._data)
        return


    ##################################################################################
    def _update(self, polydata):
        """Overwrite the polygonal mesh with a new vtkPolyData."""
        self._data = polydata
        self._mapper.SetInputData(polydata)
        self._mapper.Modified()
        return self

    def __add__(self, meshs):
        if isinstance(meshs, list):
            alist = [self]
            for l in meshs:
                if isinstance(l, vtk.vtkAssembly):
                    alist += l.getMeshes()
                else:
                    alist += l
            return vedo.assembly.Assembly(alist)
        elif isinstance(meshs, vtk.vtkAssembly):
            meshs.AddPart(self)
            return meshs
        return vedo.assembly.Assembly([self, meshs])


    def polydata(self, transformed=True):
        """
        Returns the ``vtkPolyData`` object of a ``Mesh``.

        .. note:: If ``transformed=True`` returns a copy of polydata that corresponds
            to the current mesh's position in space.
        """
        if not self._data:
            self._data = self._mapper.GetInput()
            return self._data

        if transformed:
            if self.GetIsIdentity() or self._data.GetNumberOfPoints()==0:
                # no need to do much
                return self._data
            else:
                # otherwise make a copy that corresponds to
                # the actual position in space of the mesh
                M = self.GetMatrix()
                # print(M, self.GetIsIdentity() )
                transform = vtk.vtkTransform()
                transform.SetMatrix(M)
                tp = vtk.vtkTransformPolyDataFilter()
                tp.SetTransform(transform)
                tp.SetInputData(self._data)
                tp.Update()
                return tp.GetOutput()
        else:
            return self._data


    def vertices(self, pts=None, transformed=True, copy=False):
        """Alias for ``points().``"""
        return self.points(pts, transformed, copy)


    def clone(self, deep=True, transformed=False):
        """
        Clone a ``PointCloud`` or ``Mesh`` object to make an exact copy of it.

        :param bool deep: if False only build a shallow copy of the object (faster copy).
        :param bool transformed: if True reset the current transformation of the copy to unit.

        |mirror| |mirror.py|_
        """
        poly = self.polydata(transformed)
        polyCopy = vtk.vtkPolyData()
        if deep:
            polyCopy.DeepCopy(poly)
        else:
            polyCopy.ShallowCopy(poly)

        if isinstance(self, vedo.Mesh):
            cloned = vedo.Mesh(polyCopy)
        else:
            cloned = Points(polyCopy)

        pr = vtk.vtkProperty()
        pr.DeepCopy(self.GetProperty())
        cloned.SetProperty(pr)

        if self.GetBackfaceProperty():
            bfpr = vtk.vtkProperty()
            bfpr.DeepCopy(self.GetBackfaceProperty())
            cloned.SetBackfaceProperty(bfpr)

        if not transformed:
            # assign the same transformation to the copy
            cloned.SetOrigin(self.GetOrigin())
            cloned.SetScale(self.GetScale())
            cloned.SetOrientation(self.GetOrientation())
            cloned.SetPosition(self.GetPosition())

        cloned._mapper.SetScalarVisibility(self._mapper.GetScalarVisibility())
        cloned._mapper.SetScalarRange(self._mapper.GetScalarRange())
        cloned._mapper.SetColorMode(self._mapper.GetColorMode())
        lsr = self._mapper.GetUseLookupTableScalarRange()
        cloned._mapper.SetUseLookupTableScalarRange(lsr)
        cloned._mapper.SetScalarMode(self._mapper.GetScalarMode())
        lut = self._mapper.GetLookupTable()
        if lut:
            cloned._mapper.SetLookupTable(lut)

        cloned.base = self.base
        cloned.top = self.top
        cloned.name = self.name
        if self.trail:
            n = len(self.trailPoints)
            cloned.addTrail(self.trailOffset, self.trailSegmentSize*n, n,
                            None, None, self.trail.GetProperty().GetLineWidth())
        if self.shadow:
            cloned.addShadow(self.shadowX, self.shadowY, self.shadowZ,
                             self.shadow.GetProperty().GetColor(),
                             self.shadow.GetProperty().GetOpacity())
        return cloned


    def clone2D(self, pos=(0,0), coordsys=4, scale=None,
                c=None, alpha=None, ps=2, lw=1,
                sendback=False, layer=0):
        """
        Copy a 3D Mesh into a static 2D image. Returns a ``vtkActor2D``.

            :param int coordsys: the coordinate system, options are

                0. Displays

                1. Normalized Display

                2. Viewport (origin is the bottom-left corner of the window)

                3. Normalized Viewport

                4. View (origin is the center of the window)

                5. World (anchor the 2d image to mesh)

            :param int ps: point size in pixel units

            :param int lw: line width in pixel units

            :param bool sendback: put it behind any other 3D object
        """
        msiz = self.diagonalSize()
        if scale is None:
            if settings.plotter_instance:
                sz = settings.plotter_instance.window.GetSize()
                dsiz = utils.mag(sz)
                scale = dsiz/msiz/9
            else:
                scale = 350/msiz
            #colors.printc('clone2D(): scale set to', utils.precision(scale/300,3))
        else:
            scale *= 300

        cmsh = self.clone()

        if self.color() is not None or c is not None:
            cmsh._data.GetPointData().SetScalars(None)
            cmsh._data.GetCellData().SetScalars(None)
        poly = cmsh.pos(0,0,0).scale(scale).polydata()

        mapper2d = vtk.vtkPolyDataMapper2D()
        mapper2d.SetInputData(poly)
        act2d = vtk.vtkActor2D()
        act2d.SetMapper(mapper2d)
        act2d.SetLayerNumber(layer)
        csys = act2d.GetPositionCoordinate()
        csys.SetCoordinateSystem(coordsys)
        act2d.SetPosition(pos)
        if c is not None:
            c = colors.getColor(c)
            act2d.GetProperty().SetColor(c)
        else:
            act2d.GetProperty().SetColor(cmsh.color())
        if alpha is not None:
            act2d.GetProperty().SetOpacity(alpha)
        else:
            act2d.GetProperty().SetOpacity(cmsh.alpha())
        act2d.GetProperty().SetPointSize(ps)
        act2d.GetProperty().SetLineWidth(lw)
        act2d.GetProperty().SetDisplayLocationToForeground()
        if sendback:
            act2d.GetProperty().SetDisplayLocationToBackground()

        # print(csys.GetCoordinateSystemAsString())
        # print(act2d.GetHeight(), act2d.GetWidth(), act2d.GetLayerNumber())
        return act2d


    def addTrail(self, offset=None, maxlength=None, n=50, c=None, alpha=None, lw=2):
        """Add a trailing line to mesh.
        This new mesh is accessible through `mesh.trail`.

        :param float offset: set an offset vector from the object center.

        :param float maxlength: length of trailing line in absolute units

        :param int n: number of segments to control precision

        :param float lw: line width of the trail

        .. hint:: See examples: |trail.py|_  |airplanes.py|_

            |trail|
        """
        if maxlength is None:
            maxlength = self.diagonalSize() * 20
            if maxlength == 0:
                maxlength = 1

        if self.trail is None:
            pos = self.GetPosition()
            self.trailPoints = [None] * n
            self.trailSegmentSize = maxlength / n
            self.trailOffset = offset

            ppoints = vtk.vtkPoints()  # Generate the polyline
            poly = vtk.vtkPolyData()
            ppoints.SetData(utils.numpy2vtk([pos] * n, dtype=np.float))
            poly.SetPoints(ppoints)
            lines = vtk.vtkCellArray()
            lines.InsertNextCell(n)
            for i in range(n):
                lines.InsertCellPoint(i)
            poly.SetPoints(ppoints)
            poly.SetLines(lines)

            if c is None:
                if hasattr(self, "GetProperty"):
                    col = self.GetProperty().GetColor()
                else:
                    col = (0.1, 0.1, 0.1)
            else:
                col = colors.getColor(c)

            if alpha is None:
                alpha = 1
                if hasattr(self, "GetProperty"):
                    alpha = self.GetProperty().GetOpacity()

            tline = vedo.mesh.Mesh(poly, c=col, alpha=alpha)
            tline.GetProperty().SetLineWidth(lw)
            self.trail = tline  # holds the vtkActor
        return self

    def updateTrail(self):
        if isinstance(self, vedo.shapes.Arrow):
            currentpos= self.tipPoint() # the tip of Arrow
        else:
            currentpos = np.array(self.GetPosition())

        if self.trailOffset:
            currentpos += self.trailOffset
        lastpos = self.trailPoints[-1]
        if lastpos is None:  # reset list
            self.trailPoints = [currentpos] * len(self.trailPoints)
            return
        if np.linalg.norm(currentpos - lastpos) < self.trailSegmentSize:
            return

        self.trailPoints.append(currentpos)  # cycle
        self.trailPoints.pop(0)

        tpoly = self.trail.polydata()
        tpoly.GetPoints().SetData(utils.numpy2vtk(self.trailPoints, dtype=np.float))
        return self


    def deletePoints(self, indices, renamePoints=False):
        """Delete a list of vertices identified by their index.

        :param bool renamePoints: if True, point indices and faces are renamed.
            If False, vertices are not really deleted and faces indices will
            stay unchanged (default, faster).

        |deleteMeshPoints| |deleteMeshPoints.py|_
        """
        cellIds = vtk.vtkIdList()
        self._data.BuildLinks()
        for i in indices:
            self._data.GetPointCells(i, cellIds)
            for j in range(cellIds.GetNumberOfIds()):
                self._data.DeleteCell(cellIds.GetId(j))  # flag cell

        self._data.RemoveDeletedCells()

        if renamePoints:
            coords = self.points(transformed=False)
            faces = self.faces()
            pts_inds = np.unique(faces) # flattened array

            newfaces = []
            for f in faces:
                newface=[]
                for i in f:
                    idx = np.where(pts_inds==i)[0][0]
                    newface.append(idx)
                newfaces.append(newface)

            newpoly = utils.buildPolyData(coords[pts_inds], newfaces)
            return self._update(newpoly)
        else:
            self._mapper.Modified()
            return self


    def delete(self, points=(), cells=()):
        """Delete points and/or cells from a point cloud or mesh."""
        rp = vtk.vtkRemovePolyData()

        if isinstance(points, Points):
            rp.SetInputData(self.polydata(False))
            poly = points.polydata(False)
            rp.RemoveInputData(poly)
            rp.Update()
            out = rp.GetOutput()
            return self._update(out)

        if points:
            idarr = utils.numpy2vtk(points, dtype='id')
        elif cells:
            idarr = utils.numpy2vtk(cells, dtype='id')
        else:
            # utils.printc("delete(): nothing to delete, skip.", c='y')
            return self
        rp.SetPointIds(idarr)
        rp.Update()
        out = rp.GetOutput()
        return self._update(out)



    def computeNormalsWithPCA(self, n=20, orientationPoint=None, flip=False):
        """
        Generate point normals using PCA (principal component analysis).
        Basically this estimates a local tangent plane around each sample point p
        by considering a small neighborhood of points around p, and fitting a plane
        to the neighborhood (via PCA).

        :param int n: neighborhood size to calculate the normal

        :param list orientationPoint: adjust the +/- sign of the normals so that
            the normals all point towards a specified point. If None, perform a traversal
            of the point cloud and flip neighboring normals so that they are mutually consistent.

        :param bool flip: flip all normals
        """
        poly = self.polydata()
        pcan = vtk.vtkPCANormalEstimation()
        pcan.SetInputData(poly)
        pcan.SetSampleSize(n)

        if orientationPoint is not None:
            pcan.SetNormalOrientationToPoint()
            pcan.SetOrientationPoint(orientationPoint)
        else:
            pcan.SetNormalOrientationToGraphTraversal()

        if flip:
            pcan.FlipNormalsOn()

        pcan.Update()
        out = pcan.GetOutput()
        varr = out.GetPointData().GetNormals()
        varr.SetName("Normals")
        pdt = self.polydata(False).GetPointData()
        pdt.SetNormals(varr)
        pdt.Modified()
        return self


    def alpha(self, opacity=None):
        """Set/get mesh's transparency. Same as `mesh.opacity()`."""
        if opacity is None:
            return self.GetProperty().GetOpacity()

        self.GetProperty().SetOpacity(opacity)
        bfp = self.GetBackfaceProperty()
        if bfp:
            if opacity < 1:
                self._bfprop = bfp
                self.SetBackfaceProperty(None)
            else:
                self.SetBackfaceProperty(self._bfprop)
        return self

    def opacity(self, alpha=None):
        """Set/get mesh's transparency. Same as `mesh.alpha()`."""
        return self.alpha(alpha)

    def forceOpaque(self, value=True):
        """ Force the Mesh, Line or point cloud to be treated as opaque"""
        ## force the opaque pass, fixes picking in vtk9
        # but causes other bad troubles with lines..
        self.SetForceOpaque(value)
        return self

    def forceTranslucent(self, value=True):
        """ Force the Mesh, Line or point cloud to be treated as translucent"""
        self.SetForceTranslucent(value)
        return self


    def pointSize(self, value):
        """Set/get mesh's point size of vertices. Same as `mesh.ps()`"""
        if not value:
            self.GetProperty().SetRepresentationToSurface()
        else:
            self.GetProperty().SetRepresentationToPoints()
            self.GetProperty().SetPointSize(value)
        return self

    def ps(self, pointSize=None):
        """Set/get mesh's point size of vertices. Same as `mesh.pointSize()`"""
        return self.pointSize(pointSize)

    def renderPointsAsSpheres(self, ras=True):
        """Make points look spheric or make them look as squares."""
        self.GetProperty().SetRenderPointsAsSpheres(ras)
        return self


    def color(self, c=False, alpha=None):
        """
        Set/get mesh's color.
        If None is passed as input, will use colors from active scalars.
        Same as `mesh.c()`.
        """
        # overrides base.color()
        if c is False:
            return np.array(self.GetProperty().GetColor())
        elif c is None:
            self._mapper.ScalarVisibilityOn()
            return self
        self._mapper.ScalarVisibilityOff()
        cc = colors.getColor(c)
        self.GetProperty().SetColor(cc)
        if self.trail:
            self.trail.GetProperty().SetColor(cc)
        if alpha is not None:
            self.alpha(alpha)
        return self

    def clean(self, tol=None):
        """
        Clean mesh polydata. Can also be used to decimate a mesh if ``tol`` is large.
        If ``tol=None`` only removes coincident points.

        :param tol: defines how far should be the points from each other
            in terms of fraction of the bounding box length.

        |moving_least_squares1D| |moving_least_squares1D.py|_

            |recosurface| |recosurface.py|_
        """
        poly = self.polydata(False)
        cleanPolyData = vtk.vtkCleanPolyData()
        cleanPolyData.PointMergingOn()
        cleanPolyData.ConvertLinesToPointsOn()
        cleanPolyData.ConvertPolysToLinesOn()
        cleanPolyData.ConvertStripsToPolysOn()
        cleanPolyData.SetInputData(poly)
        if tol:
            cleanPolyData.SetTolerance(tol)
        cleanPolyData.Update()
        return self._update(cleanPolyData.GetOutput())


    def threshold(self, scalars, above=None, below=None, on='points'):
        """
        Extracts cells where scalar value satisfies threshold criterion.

        :param str,list scalars: name of the scalars array.
        :param float above: minimum value of the scalar
        :param float below: maximum value of the scalar
        :param str on: if 'cells' assume array of scalars refers to cell data.

        |mesh_threshold| |mesh_threshold.py|_
        """
        if utils.isSequence(scalars):
            if on.startswith('c'):
                self.addCellArray(scalars, "threshold")
            else:
                self.addPointArray(scalars, "threshold")
            scalars = "threshold"
        else: # string is passed
            if on.startswith('c'):
                arr = self.getCellArray(scalars)
            else:
                arr = self.getPointArray(scalars)
            if arr is None:
                colors.printc("No scalars found with name/nr:", scalars, c='r')
                colors.printc("Available scalars are:\n", self.getArrayNames(), c='y')
                raise RuntimeError()

        thres = vtk.vtkThreshold()
        thres.SetInputData(self._data)

        if on.startswith('c'):
            asso = vtk.vtkDataObject.FIELD_ASSOCIATION_CELLS
        else:
            asso = vtk.vtkDataObject.FIELD_ASSOCIATION_POINTS
        thres.SetInputArrayToProcess(0, 0, 0, asso, scalars)
        #        if above is not None and below is not None:
        #            if above<below:
        #                thres.ThresholdBetween(above, below)
        #            elif above==below:
        #                return self
        #            else:
        #                thres.InvertOn()
        #                thres.ThresholdBetween(below, above)
        #        elif above is not None:
        #            thres.ThresholdByUpper(above)
        #        elif below is not None:
        #            thres.ThresholdByLower(below)

        if above is None and below is not None:
            thres.ThresholdByLower(below)
        elif below is None and above is not None:
            thres.ThresholdByUpper(above)
        else:
            thres.ThresholdBetween(above, below)
        thres.Update()

        gf = vtk.vtkGeometryFilter()
        gf.SetInputData(thres.GetOutput())
        gf.Update()
        return self._update(gf.GetOutput())


    def quantize(self, binSize):
        """
        The user should input binSize and all {x,y,z} coordinates
        will be quantized to that absolute grain size.

        Example:
            .. code-block:: python

                from vedo import Paraboloid
                Paraboloid().lw(0.1).quantize(0.1).show()
        """
        poly = self.polydata(False)
        qp = vtk.vtkQuantizePolyDataPoints()
        qp.SetInputData(poly)
        qp.SetQFactor(binSize)
        qp.Update()
        return self._update(qp.GetOutput())


    def averageSize(self):
        """Calculate the average size of a mesh.
        This is the mean of the vertex distances from the center of mass."""
        cm = self.centerOfMass()
        coords = self.points(copy=False)
        if not len(coords):
            return 0.0
        cc = coords-cm
        return np.mean(np.linalg.norm(cc, axis=1))

    def centerOfMass(self):
        """Get the center of mass of mesh.

        |fatlimb| |fatlimb.py|_
        """
        cmf = vtk.vtkCenterOfMass()
        cmf.SetInputData(self.polydata())
        cmf.Update()
        c = cmf.GetCenter()
        return np.array(c)


    def normalAt(self, i):
        """Return the normal vector at vertex point `i`."""
        normals = self.polydata().GetPointData().GetNormals()
        return np.array(normals.GetTuple(i))

    def normals(self, cells=False, compute=True):
        """Retrieve vertex normals as a numpy array.

        :params bool cells: if `True` return cell normals.

        :params bool compute: if `True` normals are recalculated if not already present.
            Note that this might modify the number of mesh points.
        """
        if cells:
            vtknormals = self.polydata().GetCellData().GetNormals()
        else:
            vtknormals = self.polydata().GetPointData().GetNormals()
        if not vtknormals and compute:
            self.computeNormals(cells=cells)
            if cells:
                vtknormals = self.polydata().GetCellData().GetNormals()
            else:
                vtknormals = self.polydata().GetPointData().GetNormals()
        if not vtknormals:
            return np.array([])
        return utils.vtk2numpy(vtknormals)


    def labels(self, content=None, cells=False, scale=None,
               rotX=0, rotY=0, rotZ=0,
               ratio=1, precision=None,
               italic=False, font="", justify="bottom-left",
               c="black", alpha=1,
        ):
        """
        Generate value or ID labels for mesh cells or points.
        For large nr. of labels use ``font="VTK"`` which is much faster.

        See also: ``flag()``, ``vignette()``, ``caption()`` and ``legend()``.

        :param list,int,str content: either 'id', array name or array number.
            A array can also be passed (must match the nr. of points or cells).

        :param bool cells: generate labels for cells instead of points [False]

        :param float scale: absolute size of labels, if left as None it is automatic

        :param float rotX: local rotation angle of label in degrees

        :param int ratio: skipping ratio, to reduce nr of labels for large meshes

        :param int precision: numeric precision of labels

        :Example:
            .. code-block:: python

                from vedo import *
                s = Sphere(alpha=0.2, res=10).lineWidth(0.1)
                s.computeNormals().clean()
                point_ids = s.labels(cells=False).c('green')
                cell_ids  = s.labels(cells=True ).c('black')
                show(s, point_ids, cell_ids)

            |meshquality| |meshquality.py|_
        """
        if cells:
            elems = self.cellCenters()
            norms = self.normals(cells=True, compute=False)
            ns = np.sqrt(self.NCells())
        else:
            elems = self.points()
            norms = self.normals(cells=False, compute=False)
            ns = np.sqrt(self.NPoints())

        hasnorms=False
        if len(norms):
            hasnorms=True

        if scale is None:
            if not ns: ns = 100
            scale = self.diagonalSize()/ns/10

        arr = None
        mode = 0
        if content is None:
            mode=0
            if cells:
                name = self._data.GetCellData().GetScalars().GetName()
                arr = self.getCellArray(name)
            else:
                name = self._data.GetPointData().GetScalars().GetName()
                arr = self.getPointArray(name)
        elif isinstance(content, (str, int)):
            if content=='id':
                mode = 1
            elif cells:
                mode=0
                arr = self.getCellArray(content)
            else:
                mode=0
                arr = self.getPointArray(content)
        elif utils.isSequence(content):
            mode = 0
            arr = content
            # print('testttt', content)  # WEIRD!
            # exit()

        if arr is None and mode == 0:
            colors.printc('Error in labels(): array not found for points/cells', c='r')
            return None

        tapp = vtk.vtkAppendPolyData()
        ninputs = 0


        for i,e in enumerate(elems):
            if i % ratio:
                continue

            if mode==1:
                txt_lab = str(i)
            else:
                if precision:
                    txt_lab = utils.precision(arr[i], precision)
                else:
                    txt_lab = str(arr[i])

            if not txt_lab:
                continue

            if font=="VTK":
                tx = vtk.vtkVectorText()
                tx.SetText(txt_lab)
                tx.Update()
                tx_poly = tx.GetOutput()
            else:
                tx_poly = vedo.shapes.Text3D(txt_lab, font=font, justify=justify).polydata(False)

            if tx_poly.GetNumberOfPoints() == 0:
                continue #######################
            ninputs += 1

            T = vtk.vtkTransform()
            T.PostMultiply()
            if italic:
                T.Concatenate([1,0.2,0,0,
                               0,1,0,0,
                               0,0,1,0,
                               0,0,0,1])
            if hasnorms:
                ni = norms[i]
                if cells: # center-justify
                    bb = tx_poly.GetBounds()
                    dx, dy = (bb[1]-bb[0])/2, (bb[3]-bb[2])/2
                    T.Translate(-dx,-dy,0)
                if rotX: T.RotateX(rotX)
                if rotY: T.RotateY(rotY)
                if rotZ: T.RotateZ(rotZ)
                crossvec = np.cross([0,0,1], ni)
                angle = np.arccos(np.dot([0,0,1], ni))*57.3
                T.RotateWXYZ(angle, crossvec)
                if cells: # small offset along normal only for cells
                    T.Translate(ni*scale/2)
            else:
                if rotX: T.RotateX(rotX)
                if rotY: T.RotateY(rotY)
                if rotZ: T.RotateZ(rotZ)
            T.Scale(scale,scale,scale)
            T.Translate(e)
            tf = vtk.vtkTransformPolyDataFilter()
            tf.SetInputData(tx_poly)
            tf.SetTransform(T)
            tf.Update()
            tapp.AddInputData(tf.GetOutput())

        if ninputs:
            tapp.Update()
            lpoly = tapp.GetOutput()
        else: #return an empty obj
            lpoly = vtk.vtkPolyData()

        ids = vedo.mesh.Mesh(lpoly, c=c, alpha=alpha)
        ids.GetProperty().LightingOff()
        return ids

    def legend(self, txt):
        """Generate legend text.

        :param str txt: legend text.

        |flag_labels|  |flag_labels.py|_
        """
        self.info['legend'] = txt
        return self

    def vignette(self,
        txt=None,
        point=None,
        offset=None,
        s=None,
        font="",
        rounded=True,
        c=None,
        alpha=1,
        lw=2,
        italic=0,
    ):
        """
        Generate and return a vignette to describe an object.
        Returns a ``Mesh`` object.

        Parameters
        ----------
        txt : str, optional
            Text to display. The default is the filename or the object name.
        point : list, optional
            position of the vignette pointer. The default is None.
        offset : list, optional
            text offset wrt the application point. The default is None.
        s : float, optional
            size of the vignette. The default is None.
        font : str, optional
            text font. The default is "".
        rounded : bool, optional
            draw a rounded or squared box around the text. The default is True.
        c : list, optional
            text and box color. The default is None.
        alpha : float, optional
            transparency of text and box. The default is 1.
        lw : float, optional
            line with of box frame. The default is 2.
        italic : float, optional
            italicness of text. The default is 0.


        |intersect2d| |intersect2d.py|_

        |goniometer| |goniometer.py|_

        |flag_labels| |flag_labels.py|_

        |intersect2d| |intersect2d.py|_
        """
        acts = []

        if txt is None:
            if self.filename:
                txt = self.filename.split('/')[-1]
            elif self.name:
                txt = self.name
            else:
                return None

        sph = None
        x0, x1, y0, y1, z0, z1 = self.bounds()
        d = self.diagonalSize()
        if point is None:
            if d:
                point = self.closestPoint([(x0 + x1) / 2, (y0 + y1) / 2, z1])
            else:  # it's a Point
                point = self.GetPosition()

        if offset is None:
            offset = [(x1 - x0) / 3, (y1 - y0) / 6, 0]
        elif len(offset) == 2:
            offset = [offset[0], offset[1], 0] # make it 3d

        if s is None:
            s = d / 20

        sph = None
        if d and (z1 - z0) / d > 0.1:
            sph = vedo.shapes.Sphere(point, r=s*0.4, res=6)

        if c is None:
            c = np.array(self.color())/1.4

        if len(point) == 2:
            point = [point[0], point[1], 0.0]
        pt = np.asarray(point)

        lb = vedo.shapes.Text3D(txt, pos=pt+offset, s=s, font=font, italic=italic, justify="bottom-left")
        acts.append(lb)

        if d and not sph:
            sph = vedo.shapes.Circle(pt, r=s/3, res=15)
        acts.append(sph)

        x0, x1, y0, y1, z0, z1 = lb.GetBounds()
        if rounded:
            box = vedo.shapes.KSpline(
                [(x0,y0,z0), (x1,y0,z0), (x1,y1,z0), (x0,y1,z0)], closed=True
            ).scale(0.91)
        else:
            box = vedo.shapes.Line(
                [(x0,y0,z0), (x1,y0,z0), (x1,y1,z0), (x0,y1,z0), (x0,y0,z0)]
            )
        box.origin([(x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2]).scale(1.2)
        acts.append(box)

        x0, x1, y0, y1, z0, z1 = box.bounds()
        if x0 < pt[0] < x1:
            c0 = box.closestPoint(pt)
            c1 = [c0[0], c0[1] + (pt[1] - y0) / 4, pt[2]]
        elif (pt[0]-x0) < (x1-pt[0]):
            c0 = [x0, (y0 + y1) / 2, pt[2]]
            c1 = [x0 + (pt[0] - x0) / 4, (y0 + y1) / 2, pt[2]]
        else:
            c0 = [x1, (y0 + y1) / 2, pt[2]]
            c1 = [x1 + (pt[0] - x1) / 4, (y0 + y1) / 2, pt[2]]

        con = vedo.shapes.Line([c0, c1, pt])
        acts.append(con)

        macts = vedo.merge(acts).c(c).alpha(alpha)
        macts.SetOrigin(pt)
        macts.bc('t').pickable(False).GetProperty().LightingOff()
        macts.GetProperty().SetLineWidth(lw)
        macts.UseBoundsOff()
        return macts

    def caption(self,
                txt=None,
                point=None,
                size=(0.30, 0.15),
                pad=5,
                font="VictorMono",
                justify="center-right",
                vspacing=1,
                c=None,
                alpha=1,
                ontop=True,
        ):
        """
        Add a 2D caption to an object which follows the camera movements.
        Latex is not supported. Returns the same input object for concatenation.

        See also ``vignette()``, ``flag()``, ``labels()`` and ``legend()``
        with similar functionality.

        Parameters
        ----------
        txt : str, optional
            text to be rendered. The default is the file name.
        point : list, optional
            anchoring point. The default is None.
        size : list, optional
            (width, height) of the caption box. The default is (0.30, 0.15).
        pad : float, optional
            padding space of the caption box in pixels. The default is 5.
        font : str, optional
            font name. Font "LogoType" allows for Japanese and Chinese characters.
            Use a monospace font for better rendering. The default is "VictorMono".
            Type ``vedo -r fonts`` for a font demo.
        justify : str, optional
            internal text justification. The default is "center-right".
        vspacing : float, optional
            vertical spacing between lines. The default is 1.
        c : str, optional
            text and box color. The default is 'lb'.
        alpha : float, optional
            text and box transparency. The default is 1.
        ontop : bool, optional
            keep the 2d caption always on top. The default is True.


        |caption| |caption.py|_

        |flag_labels|  |flag_labels.py|_
        """
        if txt is None:
            if self.filename:
                txt = self.filename.split('/')[-1]
            elif self.name:
                txt = self.name

        if not txt: # disable it
            self._caption = None
            return self

        for r in vedo.shapes._reps:
            txt = txt.replace(r[0], r[1])

        if c is None:
            c = np.array(self.GetProperty().GetColor())/2
        else:
            c = colors.getColor(c)

        if not font:
           font =  settings.defaultFont

        if point is None:
            x0,x1,y0,y1,z0,z1 = self.GetBounds()
            pt = [(x0+x1)/2, (y0+y1)/2, z1]
            point = self.closestPoint(pt)

        capt = vtk.vtkCaptionActor2D()
        capt.SetAttachmentPoint(point)
        capt.SetBorder(True)
        capt.SetLeader(True)
        sph = vtk.vtkSphereSource()
        sph.Update()
        capt.SetLeaderGlyphData(sph.GetOutput())
        capt.SetMaximumLeaderGlyphSize(5)
        capt.SetPadding(pad)
        capt.SetCaption(txt)
        capt.SetWidth(size[0])
        capt.SetHeight(size[1])
        capt.SetThreeDimensionalLeader(not ontop)

        pra = capt.GetProperty()
        pra.SetColor(c)
        pra.SetOpacity(alpha*0.5)

        pr = capt.GetCaptionTextProperty()
        pr.SetFontFamily(vtk.VTK_FONT_FILE)
        if 'LogoType' in font: # special case of big file
            fl = vedo.io.download("https://vedo.embl.es/fonts/LogoType.ttf")
        else:
            fl = settings.fonts_path + font + '.ttf'
        if not os.path.isfile(fl):
            fl = font
        pr.SetFontFile(fl)
        pr.ShadowOff()
        pr.BoldOff()
        pr.FrameOff()
        pr.SetColor(c)
        pr.SetOpacity(alpha)
        pr.SetJustificationToLeft()
        if "top" in justify:
            pr.SetVerticalJustificationToTop()
        if "bottom" in justify:
            pr.SetVerticalJustificationToBottom()
        if "cent" in justify:
            pr.SetVerticalJustificationToCentered()
            pr.SetJustificationToCentered()
        if "left" in justify:
            pr.SetJustificationToLeft()
        if "right" in justify:
            pr.SetJustificationToRight()
        pr.SetLineSpacing(vspacing)
        self._caption = capt
        return self

    def flag(self,
             text=None,
             font="Normografo",
             size=18,
             angle=0,
             shadow=False,
             c='k',
             bg='w',
             justify=0,
             delay=150,
        ):
        """
        Add a flag label which becomes visible when hovering the object with mouse.
        Can be later disabled by setting `flag(False)`.

        See also: ``labels()``, ``vignette()``, ``caption()`` and ``legend()``.

        Parameters
        ----------
        text : str, optional
            text string to be rendered. The default is the filename without extension.
        font : str, optional
            name of font to use. The default is "Courier".
        size : int, optional
            size of font. The default is 18. Fonts are: "Arial", "Courier", "Times".
        angle : float, optional
            rotation angle. The default is 0.
        shadow : bool, optional
            add a shadow to the font. The default is False.
        c : str, optional
            color name or index. The default is 'k'.
        bg : str, optional
            color name of the background. The default is 'w'.
        justify : TYPE, optional
            justification code. The default is 0.
        delay : float, optional
            pop up delay in milliseconds. The default is 150.

        |flag_labels| |flag_labels.py|_
        """
        if text is None:
            if self.filename:
                text = self.filename.split('/')[-1]
            elif self.name:
                text = self.name
            else:
                text = ""
        if "\\" in repr(text):
            for r in vedo.shapes._reps:
                text = text.replace(r[0], r[1])
        self.flagText = text
        settings.flagDelay    = delay
        settings.flagFont     = font
        settings.flagFontSize = size
        settings.flagAngle    = angle
        settings.flagShadow   = shadow
        settings.flagColor    = c
        settings.flagJustification = justify
        settings.flagBackgroundColor = bg
        return self

    def alignTo(self, target, iters=100, rigid=False,
                invert=False, useCentroids=False):
        """
        Aligned to target mesh through the `Iterative Closest Point` algorithm.

        The core of the algorithm is to match each vertex in one surface with
        the closest surface point on the other, then apply the transformation
        that modify one surface to best match the other (in the least-square sense).

        :param bool rigid: if True do not allow scaling

        :param bool invert: if True start by aligning the target to the source but
             invert the transformation finally. Useful when the target is smaller
             than the source.


        :param bool useCentroids: start by matching the centroids of the two objects.

        .. hint:: |align1.py|_ |align2.py|_

             |align1| |align2|
        """
        icp = vtk.vtkIterativeClosestPointTransform()
        icp.SetSource(self.polydata())
        icp.SetTarget(target.polydata())
        if invert:
            icp.Inverse()
        icp.SetMaximumNumberOfIterations(iters)
        if rigid:
            icp.GetLandmarkTransform().SetModeToRigidBody()
        icp.SetStartByMatchingCentroids(useCentroids)
        icp.Update()

        if invert:
            T = icp.GetMatrix() # icp.GetInverse() doesnt work!
            T.Invert()
            self.applyTransform(T)
            self.transform = T
        else:
            self.applyTransform(icp)
            self.transform = icp

        return self


    def transformWithLandmarks(self, sourceLandmarks, targetLandmarks, rigid=False):
        """
        Trasform mesh orientation and position based on a set of landmarks points.
        The algorithm finds the best matching of source points to target points
        in the mean least square sense, in one single step.
        """
        lmt = vtk.vtkLandmarkTransform()

        if utils.isSequence(sourceLandmarks):
            ss = vtk.vtkPoints()
            for p in sourceLandmarks:
                ss.InsertNextPoint(p)
        else:
            ss = sourceLandmarks.polydata().GetPoints()

        if utils.isSequence(targetLandmarks):
            st = vtk.vtkPoints()
            for p in targetLandmarks:
                st.InsertNextPoint(p)
        else:
            st = targetLandmarks.polydata().GetPoints()

        if ss.GetNumberOfPoints() != st.GetNumberOfPoints():
            colors.printc('Error in transformWithLandmarks():', c='r')
            colors.printc('Source and Target have != nr of points',
                          ss.GetNumberOfPoints(), st.GetNumberOfPoints(), c='r')
            raise RuntimeError()

        lmt.SetSourceLandmarks(ss)
        lmt.SetTargetLandmarks(st)
        if rigid:
            lmt.SetModeToRigidBody()
        lmt.Update()
        self.applyTransform(lmt)
        self.transform = lmt
        return self


    def applyTransform(self, transformation, reset=False):
        """
        Apply a linear or non-linear transformation to the mesh polygonal data.

        :param transformation: a ``vtkTransform``, ``vtkMatrix4x4``
            or a 4x4 or 3x3 python or numpy matrix.

        :param bool reset: if True reset the current transformation matrix
            to identity after having moved the object, otherwise the internal
            matrix will stay the same (to only affect visualization).
            It the input transformation has no internal defined matrix (ie. non linear)
            then reset will be assumed as True.
        """
        if isinstance(transformation, vtk.vtkMatrix4x4):
            tr = vtk.vtkTransform()
            tr.SetMatrix(transformation)
            transformation = tr
        elif utils.isSequence(transformation):
            M = vtk.vtkMatrix4x4()
            n = len(transformation[0])
            for i in range(n):
                for j in range(n):
                    M.SetElement(i, j, transformation[i][j])
            tr = vtk.vtkTransform()
            tr.SetMatrix(M)
            transformation = tr

        if reset or not hasattr(transformation, 'GetMatrix'):
            tf = vtk.vtkTransformPolyDataFilter()
            tf.SetTransform(transformation)
            tf.SetInputData(self.polydata())
            tf.Update()
            self.PokeMatrix(vtk.vtkMatrix4x4())  # reset to identity
            return self._update(tf.GetOutput())
        else:
            self.SetUserMatrix(transformation.GetMatrix())
            return self


    def normalize(self):
        """
        Scale Mesh average size to unit.
        """
        coords = self.points()
        if not len(coords):
            return self
        cm = np.mean(coords, axis=0)
        pts = coords - cm
        xyz2 = np.sum(pts * pts, axis=0)
        scale = 1 / np.sqrt(np.sum(xyz2) / len(pts))
        t = vtk.vtkTransform()
        t.Scale(scale, scale, scale)
        tf = vtk.vtkTransformPolyDataFilter()
        tf.SetInputData(self._data)
        tf.SetTransform(t)
        tf.Update()
        return self._update(tf.GetOutput())


    def mirror(self, axis="x", origin=[0,0,0], reset=False):
        """
        Mirror the mesh  along one of the cartesian axes

        :param str axis: axis to use for mirroring, must be set to x, y, z or n.
            Or any combination of those. Adding 'n' reverses mesh faces (hence normals).

        :param list origin: use this point as the origin of the mirroring transformation.

        :param bool reset: if True keep into account the current position of the object,
            and then reset its internal transformation matrix to Identity.

        |mirror| |mirror.py|_
        """
        sx, sy, sz = 1, 1, 1
        if "x" in axis.lower(): sx = -1
        if "y" in axis.lower(): sy = -1
        if "z" in axis.lower(): sz = -1
        origin = np.array(origin)
        tr = vtk.vtkTransform()
        tr.PostMultiply()
        tr.Translate(-origin)
        tr.Scale(sx, sy, sz)
        tr.Translate(origin)
        tf = vtk.vtkTransformPolyDataFilter()
        tf.SetInputData(self.polydata(reset))
        tf.SetTransform(tr)
        tf.Update()
        outpoly = tf.GetOutput()
        if reset:
            self.PokeMatrix(vtk.vtkMatrix4x4())  # reset to identity
        if sx*sy*sz<0 or 'n' in axis:
            rs = vtk.vtkReverseSense()
            rs.SetInputData(outpoly)
            rs.ReverseNormalsOff()
            rs.Update()
            outpoly = rs.GetOutput()
        return self._update(outpoly)


    def shear(self, x=0, y=0, z=0):
        """
        Apply a shear deformation to the Mesh along one of the main axes.
        """
        t = vtk.vtkTransform()
        sx, sy, sz = self.GetScale()
        t.SetMatrix([sx, x, 0, 0,
                      y,sy, z, 0,
                      0, 0,sz, 0,
                      0, 0, 0, 1])
        self.applyTransform(t, reset=True)
        return self


    def flipNormals(self):
        """
        Flip all mesh normals. Same as `mesh.mirror('n')`.
        """
        rs = vtk.vtkReverseSense()
        rs.SetInputData(self._data)
        rs.ReverseCellsOff()
        rs.ReverseNormalsOn()
        rs.Update()
        return self._update(rs.GetOutput())


    #####################################################################################
    def cmap(self,
             cname,
             input_array=None,
             on="points",
             arrayName="",
             vmin=None, vmax=None,
             alpha=1,
             n=256,
        ):
        """
        Set individual point/cell colors by providing a list of scalar values and a color map.
        `scalars` can be the string name of a ``vtkArray``.

        :param cname: color map scheme to transform a real number into a color.
        :type cname: str, list, vtkLookupTable, matplotlib.colors.LinearSegmentedColormap

        :param str on: either 'points' or 'cells'.
            Apply the color map as defined on either point or cell data.

        :param str arrayName: give a name to the array

        :param float vmin: clip scalars to this minimum value

        :param float vmax: clip scalars to this maximum value

        :param float,list alpha: mesh transparency.
            Can be a ``list`` of values one for each vertex.

        :param int n: number of distinct colors to be used.

        .. hint::|mesh_coloring.py|_ |mesh_alphas.py|_ |mesh_custom.py|_

             |mesh_coloring| |mesh_alphas| |mesh_custom|
        """
        if on.startswith('p'):
            if not arrayName: arrayName="PointScalars"
            self.pointColors(input_array, cname, alpha, vmin, vmax, arrayName, n)
        elif on.startswith('c'):
            if not arrayName: arrayName="CellScalars"
            self.cellColors(input_array, cname, alpha, vmin, vmax, arrayName, n)
        else:
            colors.printc('Must specify mode in cmap(on="either cells or points")!', c='r')
            raise RuntimeError()
        return self

    def pointColors(self,
                    input_array=None,
                    cmap="rainbow",
                    alpha=1,
                    vmin=None, vmax=None,
                    arrayName="PointScalars",
                    n=256,
        ):
        """
        DEPRECATED: use cmap() instead.
        """
        poly = self.polydata(False)

        if input_array is None:             # if None try to fetch the active scalars
            arr = poly.GetPointData().GetScalars()
            if not arr:
                colors.printc('In cmap(): cannot find any active point array ...skip coloring.', c='r')
                return self

        elif isinstance(input_array, str):  # if a name string is passed
            arr = poly.GetPointData().GetArray(input_array)
            if not arr:
                colors.printc('In cmap(): cannot find point array with name:',
                              input_array, '...skip coloring.', c='r')
                return self

        elif isinstance(input_array, int):  # if a int is passed
            if input_array < poly.GetPointData().GetNumberOfArrays():
                arr = poly.GetPointData().GetArray(input_array)
            else:
                colors.printc('In cmap(): cannot find point array at position:', input_array,
                              '...skip coloring.', c='r')
                return self

        elif utils.isSequence(input_array): # if a numpy array is passed
            npts = len(input_array)
            if npts != poly.GetNumberOfPoints():
                colors.printc('In cmap(): nr. of scalars != nr. of points',
                              n, poly.GetNumberOfPoints(), '...skip coloring.', c='r')
                return self
            arr = utils.numpy2vtk(input_array, name=arrayName)

        elif isinstance(input_array, vtk.vtkArray): # if a vtkArray is passed
            arr = input_array

        else:
            colors.printc('In cmap(): cannot understand input:', input_array, c='r')
            raise RuntimeError()

        ##########################
        arrfl = vtk.vtkFloatArray() #casting
        arrfl.ShallowCopy(arr)
        arr = arrfl

        if not arr.GetName():
            arr.SetName(arrayName)
        else:
            arrayName = arr.GetName()

        if not utils.isSequence(alpha):
            alpha = [alpha]*n

        if vmin is None:
            vmin = arr.GetRange()[0]
        if vmax is None:
            vmax = arr.GetRange()[1]

        ########################### build the look-up table
        if isinstance(cmap, vtk.vtkLookupTable): # vtkLookupTable
            lut = cmap

        elif utils.isSequence(cmap):                 # manual sequence of colors
            lut = vtk.vtkLookupTable()
            lut.SetRange(vmin,vmax)
            ncols, nalpha = len(cmap), len(alpha)
            lut.SetNumberOfTableValues(ncols)
            for i, c in enumerate(cmap):
                r, g, b = colors.getColor(c)
                idx = int(i/ncols * nalpha)
                lut.SetTableValue(i, r, g, b, alpha[idx])
            lut.Build()

        else: # assume string cmap name OR matplotlib.colors.LinearSegmentedColormap
            lut = vtk.vtkLookupTable()
            lut.SetRange(vmin,vmax)
            ncols, nalpha = n, len(alpha)
            lut.SetNumberOfTableValues(ncols)
            mycols = colors.colorMap(range(ncols), cmap, 0,ncols)
            for i,c in enumerate(mycols):
                r, g, b = c
                idx = int(i/ncols * nalpha)
                lut.SetTableValue(i, r, g, b, alpha[idx])
            lut.Build()

        self._mapper.SetLookupTable(lut)
        self._mapper.SetScalarModeToUsePointData()
        self._mapper.ScalarVisibilityOn()
        if hasattr(self._mapper, 'SetArrayName'):
            self._mapper.SetArrayName(arrayName)
        if settings.autoResetScalarRange:
            self._mapper.SetScalarRange(lut.GetRange())
        poly.GetPointData().SetScalars(arr)
        poly.GetPointData().SetActiveScalars(arrayName)
        poly.GetPointData().Modified()
        return self

    def cellColors(self,
                   input_array=None,
                   cmap="jet",
                   alpha=1,
                   vmin=None, vmax=None,
                   arrayName="CellScalars",
                   n=256,
        ):
        """
        DEPRECATED: use cmap(on='cells') instead.
        """
        poly = self.polydata(False)

        if input_array is None:             # if None try to fetch the active scalars
            arr = poly.GetCellData().GetScalars()
            if not arr:
                colors.printc('In cmap(): Cannot find any active Cell array ...skip coloring.', c='r')
                return self

        elif isinstance(input_array, str):  # if a name string is passed
            arr = poly.GetCellData().GetArray(input_array)
            if not arr:
                colors.printc('In cmap(): Cannot find Cell array with name:', input_array,
                              '...skip coloring.', c='r')
                return self

        elif isinstance(input_array, int):  # if a int is passed
            if input_array < poly.GetCellData().GetNumberOfArrays():
                arr = poly.GetCellData().GetArray(input_array)
            else:
                colors.printc('In cmap(): Cannot find Cell array at position:', input_array,
                              '...skip coloring.', c='r')
                return self

        elif utils.isSequence(input_array): # if a numpy array is passed
            npts = len(input_array)
            if npts != poly.GetNumberOfCells():
                colors.printc('In cmap(): nr. of scalars != nr. of Cells',
                              npts, poly.GetNumberOfCells(), '...skip coloring.', c='r')
                return self
            arr = utils.numpy2vtk(input_array, name=arrayName)

        elif isinstance(input_array, vtk.vtkArray): # if a vtkArray is passed
            arr = input_array

        else:
            colors.printc('In cmap(): cannot understand input:', input_array, c='r')
            raise RuntimeError()

        ##########################
        arrfl = vtk.vtkFloatArray() #casting
        arrfl.ShallowCopy(arr)
        arr = arrfl

        if not arr.GetName():
            arr.SetName(arrayName)
        else:
            arrayName = arr.GetName()

        if not utils.isSequence(alpha):
            alpha = [alpha]*n

        if vmin is None:
            vmin = arr.GetRange()[0]
        if vmax is None:
            vmax = arr.GetRange()[1]

        ########################### build the look-up table
        if isinstance(cmap, vtk.vtkLookupTable):     # vtkLookupTable
            lut = cmap

        elif utils.isSequence(cmap):                 # manual sequence of colors
            lut = vtk.vtkLookupTable()
            lut.SetRange(vmin,vmax)
            ncols, nalpha = len(cmap), len(alpha)
            lut.SetNumberOfTableValues(ncols)
            for i, c in enumerate(cmap):
                r, g, b = colors.getColor(c)
                idx = int(i/ncols * nalpha)
                lut.SetTableValue(i, r, g, b, alpha[idx])
            lut.Build()

        else: # assume string cmap name OR matplotlib.colors.LinearSegmentedColormap
            lut = vtk.vtkLookupTable()
            lut.SetRange(vmin,vmax)
            ncols, nalpha = n, len(alpha)
            lut.SetNumberOfTableValues(ncols)
            mycols = colors.colorMap(range(ncols), cmap, 0,ncols)
            for i,c in enumerate(mycols):
                r, g, b = c
                idx = int(i/ncols * nalpha)
                lut.SetTableValue(i, r, g, b, alpha[idx])
            lut.Build()

        self._mapper.SetLookupTable(lut)
        self._mapper.SetScalarModeToUseCellData()
        self._mapper.ScalarVisibilityOn()
        if hasattr(self._mapper, 'SetArrayName'):
            self._mapper.SetArrayName(arrayName)
        if settings.autoResetScalarRange:
            self._mapper.SetScalarRange(lut.GetRange())
        poly.GetCellData().SetScalars(arr)
        poly.GetCellData().SetActiveScalars(arrayName)
        poly.GetCellData().Modified()
        return self


    def cellIndividualColors(self, colorlist, alpha=1, alphaPerCell=False):
        """
        Colorize the faces of a mesh one by one
        passing a 1-to-1 list of colors and optionally a list of transparencies.

        :param bool alphaPerCell: Only matters if `alpha` is a sequence. If so:
            if `True` assume that the list of opacities is independent
            on the colors (same color cells can have different opacity),
            this can be very slow for large meshes,

            if `False` [default] assume that the alpha matches the color list
            (same color has the same opacity).
            This is very fast even for large meshes.
        """
        cellData = vtk.vtkUnsignedIntArray()
        cellData.SetName("CellIndividualColors")

        n = self._data.GetNumberOfCells()
        if len(colorlist) != n or (utils.isSequence(alpha) and len(alpha) != n):
            colors.printc("Error in cellIndividualColors(): mismatch in input list sizes.",
                          len(colorlist), n, c='r')
            return self

        lut = vtk.vtkLookupTable()
        if alphaPerCell:
            lut.SetNumberOfTableValues(n)
            lut.Build()
            cols = colors.getColor(colorlist)
            if not utils.isSequence(alpha):
                alpha = [alpha] * n
            for i in range(n):
                cellData.InsertNextValue(i)
                c = cols[i]
                lut.SetTableValue(i, c[0], c[1], c[2], alpha[i])
        else:
            ucolors, uids, inds = np.unique(colorlist, axis=0,
                                            return_index=True, return_inverse=True)
            nc = len(ucolors)

            if nc == 1:
                self.color(colors.getColor(ucolors[0]))
                if utils.isSequence(alpha):
                    self.alpha(alpha[0])
                else:
                    self.alpha(alpha)
                return self

            for i in range(n):
                cellData.InsertNextValue(int(inds[i]))

            lut.SetNumberOfTableValues(nc)
            lut.Build()

            cols = colors.getColor(ucolors)

            if not utils.isSequence(alpha):
                alpha = np.ones(n)

            for i in range(nc):
                c = cols[i]
                lut.SetTableValue(i, c[0], c[1], c[2], alpha[uids[i]])

        self._data.GetCellData().SetScalars(cellData)
        self._data.GetCellData().Modified()
        self._mapper.SetScalarRange(0, lut.GetNumberOfTableValues()-1)
        self._mapper.SetLookupTable(lut)
        if hasattr(self._mapper, 'SetArrayName'):
            self._mapper.SetArrayName("CellColors")
        self._mapper.SetScalarModeToUseCellData()
        self._mapper.ScalarVisibilityOn()
        return self

    def interpolateDataFrom(self, source,
                            radius=None, N=None,
                            kernel='shepard',
                            exclude=('Normals',),
                            nullStrategy=1,
                            nullValue=0,
        ):
        """
        Interpolate over source to port its data onto the current object using various kernels.

        If N (number of closest points to use) is set then radius value is ignored.

        :param str kernel: available kernels are [shepard, gaussian, linear]

        :param int nullStrategy: specify a strategy to use when encountering a "null" point
            during the interpolation process. Null points occur when the local neighborhood
            (of nearby points to interpolate from) is empty.
            Case 0: an output array is created that marks points
            as being valid (=1) or null (invalid =0), and the nullValue is set as well
            Case 1: the output data value(s) are set to the provided nullValue
            Case 2: simply use the closest point to perform the interpolation.

        :param float nullValue: see above.
        """
        if radius is None and not N:
            colors.printc("Error in interpolateDataFrom(): please set either radius or N", c='r')
            raise RuntimeError

        points = source.polydata()

        locator = vtk.vtkPointLocator()
        locator.SetDataSet(points)
        locator.BuildLocator()

        if kernel.lower() == 'shepard':
            kern = vtk.vtkShepardKernel()
            kern.SetPowerParameter(2)
        elif kernel.lower() == 'gaussian':
            kern = vtk.vtkGaussianKernel()
            kern.SetSharpness(2)
        elif kernel.lower() == 'linear':
            kern = vtk.vtkLinearKernel()
        else:
            colors.printc('Error in interpolateDataFrom(), available kernels are:', c='r')
            colors.printc(' [shepard, gaussian, linear]', c='r')
            raise RuntimeError()

        if N:
            kern.SetNumberOfPoints(N)
            kern.SetKernelFootprintToNClosest()
        else:
            kern.SetRadius(radius)

        interpolator = vtk.vtkPointInterpolator()
        interpolator.SetInputData(self.polydata())
        interpolator.SetSourceData(points)
        interpolator.SetKernel(kern)
        interpolator.SetLocator(locator)
        interpolator.PassFieldArraysOff()
        interpolator.SetNullPointsStrategy(nullStrategy)
        interpolator.SetNullValue(nullValue)
        interpolator.SetValidPointsMaskArrayName("ValidPointMask")
        for ex in exclude:
            interpolator.AddExcludedArray(ex)
        interpolator.Update()
        cpoly = interpolator.GetOutput()

        if self.GetIsIdentity() or cpoly.GetNumberOfPoints() == 0:
            self._update(cpoly)
        else:
            # bring the underlying polydata to where _data is
            M = vtk.vtkMatrix4x4()
            M.DeepCopy(self.GetMatrix())
            M.Invert()
            tr = vtk.vtkTransform()
            tr.SetMatrix(M)
            tf = vtk.vtkTransformPolyDataFilter()
            tf.SetTransform(tr)
            tf.SetInputData(cpoly)
            tf.Update()
            self._update(tf.GetOutput())

        return self


    def pointGaussNoise(self, sigma):
        """
        Add gaussian noise to point positions.

        :param float sigma: sigma is expressed in percent of the diagonal size of mesh.
            Can be a list [sigma_x, sigma_y, sigma_z].

        :Example:
            .. code-block:: python

                from vedo import Sphere

                Sphere().pointGaussNoise(1.0).show()
        """
        sz = self.diagonalSize()
        pts = self.points()
        n = len(pts)
        ns = (np.random.randn(n, 3) * sigma) * (sz / 100)
        vpts = vtk.vtkPoints()
        vpts.SetNumberOfPoints(n)
        vpts.SetData(utils.numpy2vtk(pts + ns))
        self._data.SetPoints(vpts)
        self._data.GetPoints().Modified()
        self.addPointArray(-ns, 'GaussNoise')
        return self


    def closestPoint(self, pt, N=1, radius=None,
                     returnPointId=False, returnCellId=False, returnIds=None
        ):
        """
        Find the closest point(s) on a mesh given from the input point `pt`.

        :param int N: if greater than 1, return a list of N ordered closest points
        :param float radius: if given, get all points within that radius.
        :param bool returnPointId: return point ID instead of coordinates
        :param bool returnCellId: return cell ID in which the closest point sits
        :param bool returnIds: obsolete, do not use.

        .. hint:: |align1.py|_ |fitplanes.py|_  |quadratic_morphing.py|_

            |align1| |quadratic_morphing|

        .. note:: The appropriate tree search locator is built on the
            fly and cached for speed. If the object is displaced/rotated you must
            trigger a rebuild by setting
            ``obj.point_locator=None`` or
            ``obj.cell_locator=None``.
        """
        if returnIds is not None:
            colors.printc("ERROR returnIds is now obsolete. Use either returnPointId or returnCellId", c='r')
            raise RuntimeError

        if (N > 1 or radius) or (N==1 and returnPointId):
            poly = None
            if not self.point_locator:
                poly = self.polydata()
                self.point_locator = vtk.vtkPointLocator()
                self.point_locator.SetDataSet(poly)
                self.point_locator.BuildLocator()

            if radius:
                vtklist = vtk.vtkIdList()
                self.point_locator.FindPointsWithinRadius(radius, pt, vtklist)
            elif N > 1:
                vtklist = vtk.vtkIdList()
                self.point_locator.FindClosestNPoints(N, pt, vtklist)
            else: # N==1 hence returnPointId==True
                ########
                return self.point_locator.FindClosestPoint(pt)
                ########

            if returnPointId:
                ########
                return [int(vtklist.GetId(k)) for k in range(vtklist.GetNumberOfIds())]
                ########
            else:
                if not poly:
                    poly = self.polydata()
                trgp = []
                for i in range(vtklist.GetNumberOfIds()):
                    trgp_ = [0, 0, 0]
                    vi = vtklist.GetId(i)
                    poly.GetPoints().GetPoint(vi, trgp_)
                    trgp.append(trgp_)
                ########
                return np.array(trgp)
                ########

        else:

            if not self.cell_locator:
                poly = self.polydata()
                self.cell_locator = vtk.vtkCellLocator()
                self.cell_locator.SetDataSet(poly)
                self.cell_locator.BuildLocator()
            trgp = [0, 0, 0]
            cid = vtk.mutable(0)
            dist2 = vtk.mutable(0)
            subid = vtk.mutable(0)
            self.cell_locator.FindClosestPoint(pt, trgp, cid, subid, dist2)
            if returnCellId:
                return int(cid)
            else:
                return np.array(trgp)


    def smoothMLS1D(self, f=0.2, radius=None):
        """
        Smooth mesh or points with a `Moving Least Squares` variant.
        The list ``mesh.info['variances']`` contain the residue calculated for each point.
        Input mesh's polydata is modified.

        :param float f: smoothing factor - typical range is [0,2].

        :param float radius: radius search in absolute units. If set then ``f`` is ignored.

        .. hint:: |moving_least_squares1D.py|_  |skeletonize.py|_

            |moving_least_squares1D| |skeletonize|
        """
        coords = self.points()
        ncoords = len(coords)

        if radius:
            Ncp=0
        else:
            Ncp = int(ncoords * f / 10)
            if Ncp < 5:
                colors.printc("Please choose a fraction higher than " + str(f), c='r')
                Ncp = 5

        variances, newline = [], []
        for p in coords:
            points = self.closestPoint(p, N=Ncp, radius=radius)
            if len(points) < 4:
                continue

            points = np.array(points)
            pointsmean = points.mean(axis=0)  # plane center
            uu, dd, vv = np.linalg.svd(points - pointsmean)
            newp = np.dot(p - pointsmean, vv[0]) * vv[0] + pointsmean
            variances.append(dd[1] + dd[2])
            newline.append(newp)

        self.info["variances"] = np.array(variances)
        return self.points(newline)


    def smoothMLS2D(self, f=0.2, radius=None):
        """
        Smooth mesh or points with a `Moving Least Squares` algorithm variant.
        The list ``mesh.info['variances']`` contains the residue calculated for each point.
        When a radius is specified points that are isolated will not be moved and will get
        a False entry in array ``mesh.info['isvalid']``.

        :param float f: smoothing factor - typical range is [0,2].

        :param float radius: radius search in absolute units. If set then ``f`` is ignored.

        .. hint:: |moving_least_squares2D.py|_  |recosurface.py|_

            |moving_least_squares2D| |recosurface|
        """
        coords = self.points()
        ncoords = len(coords)

        if radius:
            Ncp = 1
        else:
            Ncp = int(ncoords * f / 100)
            if Ncp < 4:
                colors.printc(f"MLS2D: Please choose a fraction higher than {f}", c='r')
                Ncp = 4

        variances, newpts, valid = [], [], []
        pb = None
        if ncoords > 10000:
            pb = utils.ProgressBar(0, ncoords)
        for i, p in enumerate(coords):
            if pb:
                pb.print("smoothMLS2D working ...")
            pts = self.closestPoint(p, N=Ncp, radius=radius)
            if len(pts) > 3:
                ptsmean = pts.mean(axis=0)  # plane center
                _, dd, vv = np.linalg.svd(pts - ptsmean)
                cv = np.cross(vv[0], vv[1])
                t = (np.dot(cv, ptsmean) - np.dot(cv, p)) / np.dot(cv,cv)
                newp = p + cv*t
                newpts.append(newp)
                variances.append(dd[2])
                if radius:
                    valid.append(True)
            else:
                newpts.append(p)
                variances.append(0)
                if radius:
                    valid.append(False)

        self.info["variances"] = np.array(variances)
        self.info["isvalid"] = np.array(valid)
        return self.points(newpts)


    def projectOnPlane(self, plane='z', point=None, direction=None):
        """
        Project the mesh on one of the Cartesian planes.

        :param str,Plane plane: if plane is `str`, plane can be one of x-plane,
            y-plane and z-plane. Otherwise, plane should be an instance of `vedo.shapes.Plane`.

        :param array point: camera point of perspective projection

        :param array direction: direction of oblique projection

        Note:
            Parameters `point` and `direction` are only used if the given plane
            is an instance of `vedo.shapes.Plane`. And one of these two params
            should be left as `None` to specify the projection type.

        Example:
            >>> s.projectOnPlane(plane='z') # project to z-plane
            >>> plane = Plane(pos=(4, 8, -4), normal=(-1, 0, 1), sx=5)
            >>> s.projectOnPlane(plane=plane)                       # orthogonal projection
            >>> s.projectOnPlane(plane=plane, point=(6, 6, 6))      # perspective projection
            >>> s.projectOnPlane(plane=plane, direction=(1, 2, -1)) # oblique projection
        """
        coords = self.points()

        if   'x' == plane:
            coords[:, 0] = self.GetOrigin()[0]
            self.x(self.xbounds()[0])
        elif 'y' == plane:
            coords[:, 1] = self.GetOrigin()[1]
            self.y(self.ybounds()[0])
        elif 'z' == plane:
            coords[:, 2] = self.GetOrigin()[2]
            self.z(self.zbounds()[0])

        elif isinstance(plane, vedo.shapes.Plane):
            normal = plane.normal / np.linalg.norm(plane.normal)
            pl = np.hstack((normal, -np.dot(plane.pos(), normal))).reshape(4, 1)
            if direction is None and point is None:
                # orthogonal projection
                pt = np.hstack((normal, [0])).reshape(4, 1)
                # proj_mat = pt.T @ pl * np.eye(4) - pt @ pl.T # python3 only
                proj_mat = np.matmul(pt.T, pl) * np.eye(4) - np.matmul(pt, pl.T)

            elif direction is None:
                # perspective projection
                pt = np.hstack((np.array(point), [1])).reshape(4, 1)
                # proj_mat = pt.T @ pl * np.eye(4) - pt @ pl.T
                proj_mat = np.matmul(pt.T, pl) * np.eye(4) - np.matmul(pt, pl.T)

            elif point is None:
                # oblique projection
                pt = np.hstack((np.array(direction), [0])).reshape(4, 1)
                # proj_mat = pt.T @ pl * np.eye(4) - pt @ pl.T
                proj_mat = np.matmul(pt.T, pl) * np.eye(4) - np.matmul(pt, pl.T)

            coords = np.concatenate([coords, np.ones((coords.shape[:-1] + (1,)))], axis=-1)
            # coords = coords @ proj_mat.T
            coords = np.matmul(coords, proj_mat.T)
            coords = coords[:, :3] / coords[:, 3:]

        else:
            colors.printc("Error in projectOnPlane(): unknown plane", plane, c='r')
            raise RuntimeError()

        self.alpha(0.1)
        self.points(coords)
        return self


    def warpToPoint(self, point, factor=0.1, absolute=True):
        """
        Modify the mesh coordinates by moving the vertices towards a specified point.

        :param float factor: value to scale displacement.
        :param list point: the position to warp towards.
        :param bool absolute: turning on causes scale factor of the new position
            to be one unit away from point.

        :Example:
            .. code-block:: python

                from vedo import *
                s = Cylinder(height=3).wireframe()
                pt = [4,0,0]
                w = s.clone().warpToPoint(pt, factor=0.5).wireframe(False)
                show(w,s, Point(pt), axes=1)

            |warpto|
        """
        warpTo = vtk.vtkWarpTo()
        warpTo.SetInputData(self._data)
        warpTo.SetPosition(point-self.pos())
        warpTo.SetScaleFactor(factor)
        warpTo.SetAbsolute(absolute)
        warpTo.Update()
        return self._update(warpTo.GetOutput())

    def warpByVectors(self, vects, factor=1, useCells=False):
        """Modify point coordinates by moving points along vector times the scale factor.
        Useful for showing flow profiles or mechanical deformation.
        Input can be an existing point/cell data array or a new array, in this case
        it will be named 'WarpVectors'.

        :parameter float factor: value to scale displacement

        :parameter bool useCell: if True, look for cell array instead of point array

        Example:
            .. code-block:: python

                from vedo import *
                b = load(datadir+'dodecahedron.vtk').computeNormals()
                b.warpByVectors("Normals", factor=0.15).show()

            |warpv|
        """
        wf = vtk.vtkWarpVector()
        wf.SetInputDataObject(self.polydata())

        if useCells:
            asso = vtk.vtkDataObject.FIELD_ASSOCIATION_CELLS
        else:
            asso = vtk.vtkDataObject.FIELD_ASSOCIATION_POINTS

        vname = vects
        if utils.isSequence(vects):
            varr = utils.numpy2vtk(vects)
            vname = "WarpVectors"
            if useCells:
                self.addCellArray(varr, vname)
            else:
                self.addPointArray(varr, vname)
        wf.SetInputArrayToProcess(0, 0, 0, asso, vname)
        wf.SetScaleFactor(factor)
        wf.Update()
        return self._update(wf.GetOutput())


    def thinPlateSpline(self, sourcePts, targetPts, sigma=1, mode="3d", funcs=(None,None)):
        """
        `Thin Plate Spline` transformations describe a nonlinear warp transform defined by a set
        of source and target landmarks. Any point on the mesh close to a source landmark will
        be moved to a place close to the corresponding target landmark.
        The points in between are interpolated smoothly using
        Bookstein's Thin Plate Spline algorithm.

        Transformation object can be accessed with ``mesh.transform``.

        :param float sigma: specify the 'stiffness' of the spline.
        :param str mode: set the basis function to either abs(R) (for 3d) or R2LogR (for 2d meshes)
        :param funcs: You may supply both the function and its derivative with respect to r.

        .. hint:: Examples: |thinplate_morphing1.py|_ |thinplate_morphing2.py|_
            |thinplate_grid.py|_ |thinplate_morphing_2d.py|_ |interpolateField.py|_

            |thinplate_morphing1| |thinplate_morphing2| |thinplate_grid|
            |interpolateField| |thinplate_morphing_2d|
        """
        if isinstance(sourcePts, Points):
            sourcePts = sourcePts.points()
        if isinstance(targetPts, Points):
            targetPts = targetPts.points()

        ns = len(sourcePts)
        ptsou = vtk.vtkPoints()
        ptsou.SetNumberOfPoints(ns)
        for i in range(ns):
            ptsou.SetPoint(i, sourcePts[i])

        nt = len(targetPts)
        if ns != nt:
            colors.printc("Error in thinPlateSpline(): #source != #target points", ns, nt, c='r')
            raise RuntimeError()

        pttar = vtk.vtkPoints()
        pttar.SetNumberOfPoints(nt)
        for i in range(ns):
            pttar.SetPoint(i, targetPts[i])

        transform = vtk.vtkThinPlateSplineTransform()
        if mode.lower() == "3d":
            transform.SetBasisToR()
        elif mode.lower() == "2d":
            transform.SetBasisToR2LogR()
        else:
            colors.printc("Error in thinPlateSpline(): unknown mode", mode, c='r')
            raise RuntimeError()
        if funcs[0]:
            transform.SetBasisFunction(funcs[0])
            transform.SetBasisDerivative(funcs[1])
        transform.SetSigma(sigma)
        transform.SetSourceLandmarks(ptsou)
        transform.SetTargetLandmarks(pttar)
        self.transform = transform
        self.applyTransform(transform, reset=True)
        return self


    def cutWithPlane(self, origin=(0, 0, 0), normal=(1, 0, 0)):
        """
        Cut the mesh with the plane defined by a point and a normal.

        :param origin: the cutting plane goes through this point
        :param normal: normal of the cutting plane

        :Example:
            .. code-block:: python

                from vedo import Cube
                cube = Cube().cutWithPlane(normal=(1,1,1))
                cube.bc('pink').show()

            |cutcube|

        |trail| |trail.py|_

        Check out also:
            ``crop()``, ``cutWithBox()``, ``cutWithCylinder()``, ``cutWithSphere()``
        """
        s = str(normal)
        if "x" in s:
            normal = (1, 0, 0)
            if '-' in s: normal = -np.array(normal)
        elif "y" in s:
            normal = (0, 1, 0)
            if '-' in s: normal = -np.array(normal)
        elif "z" in s:
            normal = (0, 0, 1)
            if '-' in s: normal = -np.array(normal)
        plane = vtk.vtkPlane()
        plane.SetOrigin(origin)
        plane.SetNormal(normal)

        clipper = vtk.vtkClipPolyData()
        clipper.SetInputData(self.polydata(True)) # must be True
        clipper.SetClipFunction(plane)
        clipper.GenerateClippedOutputOff()
        clipper.GenerateClipScalarsOff()
        clipper.SetValue(0)
        clipper.Update()

        cpoly = clipper.GetOutput()

        if self.GetIsIdentity() or cpoly.GetNumberOfPoints() == 0:
            self._update(cpoly)
        else:
            # bring the underlying polydata to where _data is
            M = vtk.vtkMatrix4x4()
            M.DeepCopy(self.GetMatrix())
            M.Invert()
            tr = vtk.vtkTransform()
            tr.SetMatrix(M)
            tf = vtk.vtkTransformPolyDataFilter()
            tf.SetTransform(tr)
            tf.SetInputData(cpoly)
            tf.Update()
            self._update(tf.GetOutput())

        return self


    def cutWithBox(self, bounds, invert=False):
        """
        Cut the current mesh with a box.
        This is much faster than ``cutWithMesh()``.

        Input ``bounds`` can be either:
            - a Mesh or Points object
            - a list of 6 number representing a bounding box [xmin,xmax, ymin,ymax, zmin,zmax]
            - a list of bounding boxes like the above: [[xmin1,...], [xmin2,...], ...]

        :Example:
            .. code-block:: python

                from vedo import Sphere, Cube, show
                mesh = Sphere(r=1, res=50)
                box  = Cube(side=1.5).wireframe()
                mesh.cutWithBox(box)
                show(mesh, box, axes=1)

        Check out also:
            ``crop()``, ``cutWithLine()``, ``cutWithPlane()``, ``cutWithCylinder()``
        """
        if isinstance(bounds, Points):
            bounds = bounds.GetBounds()

        box = vtk.vtkBox()
        if utils.isSequence(bounds[0]):
            for bs in bounds:
                box.AddBounds(bs)
        else:
            box.SetBounds(bounds)

        clipper = vtk.vtkClipPolyData()
        clipper.SetInputData(self.polydata(True)) # must be True
        clipper.SetClipFunction(box)
        clipper.SetInsideOut(not invert)
        clipper.GenerateClippedOutputOff()
        clipper.GenerateClipScalarsOff()
        clipper.SetValue(0)
        clipper.Update()
        cpoly = clipper.GetOutput()

        if self.GetIsIdentity() or cpoly.GetNumberOfPoints() == 0:
            self._update(cpoly)
        else:
            # bring the underlying polydata to where _data is
            M = vtk.vtkMatrix4x4()
            M.DeepCopy(self.GetMatrix())
            M.Invert()
            tr = vtk.vtkTransform()
            tr.SetMatrix(M)
            tf = vtk.vtkTransformPolyDataFilter()
            tf.SetTransform(tr)
            tf.SetInputData(cpoly)
            tf.Update()
            self._update(tf.GetOutput())

        return self

    def cutWithLine(self, points, invert=False):
        """
        Cut the current mesh with a line vertically in the z-axis direction.
        The polyline is defined by a set of points (z-coordinates are ignored).
        This is much faster than ``cutWithMesh()``.

        Check out also:
            ``crop()``, ``cutWithBox()``, ``cutWithPlane()``, ``cutWithSphere()``
        """
        pplane = vtk.vtkPolyPlane()
        if isinstance(points, Points):
            points = points.points()

        vpoints = vtk.vtkPoints()
        for p in points:
            vpoints.InsertNextPoint(p)

        n = len(points)
        polyLine = vtk.vtkPolyLine()
        polyLine.Initialize(n, vpoints)
        polyLine.GetPointIds().SetNumberOfIds(n)
        for i in range(n):
            polyLine.GetPointIds().SetId(i, i)
        pplane.SetPolyLine(polyLine)

        clipper = vtk.vtkClipPolyData()
        clipper.SetInputData(self.polydata(True)) # must be True
        clipper.SetClipFunction(pplane)
        clipper.SetInsideOut(invert)
        clipper.GenerateClippedOutputOff()
        clipper.GenerateClipScalarsOff()
        clipper.SetValue(0)
        clipper.Update()
        cpoly = clipper.GetOutput()

        if self.GetIsIdentity() or cpoly.GetNumberOfPoints() == 0:
            self._update(cpoly)
        else:
            # bring the underlying polydata to where _data is
            M = vtk.vtkMatrix4x4()
            M.DeepCopy(self.GetMatrix())
            M.Invert()
            tr = vtk.vtkTransform()
            tr.SetMatrix(M)
            tf = vtk.vtkTransformPolyDataFilter()
            tf.SetTransform(tr)
            tf.SetInputData(cpoly)
            tf.Update()
            self._update(tf.GetOutput())

        return self

    def cutWithCylinder(self, center=(0,0,0), axis=(0,0,1), r=1, invert=False):
        """
        Cut the current mesh with an infinite cylinder.
        This is much faster than ``cutWithMesh()``.

        :param list center: the center of the cylinder
        :param list normal: direction of the cylinder axis
        :param float r: radius of the cylinder

        :Example:
            .. code-block:: python

                from vedo import Disc, show
                disc = Disc(r1=1, r2=1.2)
                mesh = disc.extrude(3, res=50).lineWidth(1)
                mesh.cutWithCylinder([0,0,2], r=0.4, axis='y', invert=True)
                show(mesh, axes=1)

        Check out also:
            ``crop()``, ``cutWithBox()``, ``cutWithPlane()``, ``cutWithSphere()``
        """
        s = str(axis)
        if "x" in s:
            axis = (1, 0, 0)
        elif "y" in s:
            axis = (0, 1, 0)
        elif "z" in s:
            axis = (0, 0, 1)
        cyl = vtk.vtkCylinder()
        cyl.SetCenter(center)
        cyl.SetAxis(axis[0], axis[1], axis[2])
        cyl.SetRadius(r)

        clipper = vtk.vtkClipPolyData()
        clipper.SetInputData(self.polydata(True)) # must be True
        clipper.SetClipFunction(cyl)
        clipper.SetInsideOut(not invert)
        clipper.GenerateClippedOutputOff()
        clipper.GenerateClipScalarsOff()
        clipper.SetValue(0)
        clipper.Update()
        cpoly = clipper.GetOutput()

        if self.GetIsIdentity() or cpoly.GetNumberOfPoints() == 0:
            self._update(cpoly)
        else:
            # bring the underlying polydata to where _data is
            M = vtk.vtkMatrix4x4()
            M.DeepCopy(self.GetMatrix())
            M.Invert()
            tr = vtk.vtkTransform()
            tr.SetMatrix(M)
            tf = vtk.vtkTransformPolyDataFilter()
            tf.SetTransform(tr)
            tf.SetInputData(cpoly)
            tf.Update()
            self._update(tf.GetOutput())

        return self

    def cutWithSphere(self, center=(0,0,0), r=1, invert=False):
        """
        Cut the current mesh with an sphere.
        This is much faster than ``cutWithMesh()``.

        :param list center: the center of the sphere
        :param float r: radius of the sphere

        :Example:
            .. code-block:: python

                from vedo import Disc, show
                disc = Disc(r1=1, r2=1.2)
                mesh = disc.extrude(3, res=50).lineWidth(1)
                mesh.cutWithSphere([1,-0.7,2], r=0.5, invert=True)
                show(mesh, axes=1)

        Check out also:
            ``crop()``, ``cutWithBox()``, ``cutWithPlane()``, ``cutWithCylinder()``
        """
        sph = vtk.vtkSphere()
        sph.SetCenter(center)
        sph.SetRadius(r)

        clipper = vtk.vtkClipPolyData()
        clipper.SetInputData(self.polydata(True)) # must be True
        clipper.SetClipFunction(sph)
        clipper.SetInsideOut(not invert)
        clipper.GenerateClippedOutputOff()
        clipper.GenerateClipScalarsOff()
        clipper.SetValue(0)
        clipper.Update()
        cpoly = clipper.GetOutput()

        if self.GetIsIdentity() or cpoly.GetNumberOfPoints() == 0:
            self._update(cpoly)
        else:
            # bring the underlying polydata to where _data is
            M = vtk.vtkMatrix4x4()
            M.DeepCopy(self.GetMatrix())
            M.Invert()
            tr = vtk.vtkTransform()
            tr.SetMatrix(M)
            tf = vtk.vtkTransformPolyDataFilter()
            tf.SetTransform(tr)
            tf.SetInputData(cpoly)
            tf.Update()
            self._update(tf.GetOutput())

        return self


    def cutWithMesh(self, mesh, invert=False):
        """
        Cut an ``Mesh`` mesh with another ``Mesh``.

        :param bool invert: if True return cut off part of Mesh.

        .. code-block:: python

            from vedo import *
            import numpy as np
            x, y, z = np.mgrid[:30, :30, :30] / 15
            U = sin(6*x)*cos(6*y) + sin(6*y)*cos(6*z) + sin(6*z)*cos(6*x)
            iso = Volume(U).isosurface(0).smoothLaplacian().c('silver').lw(1)
            cube = CubicGrid(n=(29,29,29), spacing=(1,1,1))
            cube.cutWithMesh(iso).c('silver').alpha(1)
            show(iso, cube)

        .. hint:: |cutWithMesh1.py|_ |cutAndCap.py|_

            |cutWithMesh1| |cutAndCap|

       Check out also:
           ``crop()``, ``cutWithBox()``, ``cutWithPlane()``, ``cutWithCylinder()``
       """
        polymesh = mesh.polydata()
        poly = self.polydata()

        # Create an array to hold distance information
        signedDistances = vtk.vtkFloatArray()
        signedDistances.SetNumberOfComponents(1)
        signedDistances.SetName("SignedDistances")

        # implicit function that will be used to slice the mesh
        ippd = vtk.vtkImplicitPolyDataDistance()
        ippd.SetInput(polymesh)

        # Evaluate the signed distance function at all of the grid points
        for pointId in range(poly.GetNumberOfPoints()):
            p = poly.GetPoint(pointId)
            signedDistance = ippd.EvaluateFunction(p)
            signedDistances.InsertNextValue(signedDistance)

        currentscals = poly.GetPointData().GetScalars()
        if currentscals:
            currentscals = currentscals.GetName()

        poly.GetPointData().AddArray(signedDistances)
        poly.GetPointData().SetActiveScalars("SignedDistances")

        clipper = vtk.vtkClipPolyData()
        clipper.SetInputData(poly)
        clipper.SetInsideOut(not invert)
        clipper.SetValue(0.0)
        clipper.Update()
        cpoly = clipper.GetOutput()

        vis = False
        if currentscals:
            cpoly.GetPointData().SetActiveScalars(currentscals)
            vis = self._mapper.GetScalarVisibility()

        if self.GetIsIdentity() or cpoly.GetNumberOfPoints() == 0:
            self._update(cpoly)
        else:
            # bring the underlying polydata to where _data is
            M = vtk.vtkMatrix4x4()
            M.DeepCopy(self.GetMatrix())
            M.Invert()
            tr = vtk.vtkTransform()
            tr.SetMatrix(M)
            tf = vtk.vtkTransformPolyDataFilter()
            tf.SetTransform(tr)
            tf.SetInputData(clipper.GetOutput())
            tf.Update()
            self._update(tf.GetOutput())

        self.removePointArray("SignedDistances")
        self._mapper.SetScalarVisibility(vis)
        return self

    def implicitModeller(self, distance=0.05, res=(50,50,50), bounds=(), maxdist=None):
        """Find the surface which sits at the specified distance from the input one."""
        if not len(bounds):
            bounds = self.bounds()

        if not maxdist:
            maxdist = self.diagonalSize()/2

        imp = vtk.vtkImplicitModeller()
        imp.SetInputData(self.polydata())
        imp.SetSampleDimensions(res)
        imp.SetMaximumDistance(maxdist)
        imp.SetModelBounds(bounds)
        contour = vtk.vtkContourFilter()
        contour.SetInputConnection(imp.GetOutputPort())
        contour.SetValue(0, distance)
        contour.Update()
        poly = contour.GetOutput()
        return vedo.Mesh(poly, c='lb')

    def tomesh( self,
                resLine=None,
                resMesh=None,
                smooth=0,
                jitter=0.01,
                grid=None,
                quads=False,
                invert=False,
                verbose=False,
        ):
        """
        Generate a polygonal Mesh from a closed contour line.
        If line is not closed it will be closed with a straight segment.

        Parameters
        ----------
        resLine : int, optional
            resolution of the contour line. The default is None, in this case
            the contour is not resampled.
        resMesh : int, optional
            resolution of the intenal triangles not touching the boundary.
            The default is None.
        smooth : float, optional
            smoothing of the contour before meshing. The default is 0.
        jitter : float, optional
            add a small noise to the internal points. The default is 0.01.
        grid : Grid, optional
            manually pass a Grid object.
            The default is True.
        quads : bool, optional
            generate a mesh of quads instead of triangles.
        invert : bool, optional
            flip the line orientation. The default is False.
        verbose : bool, optional
            printout info during the process. The default is False.
        """
        if resLine is None:
            contour = vedo.shapes.Line(self.points())
        else:
            contour = vedo.shapes.Spline(self.points(), smooth=smooth, res=resLine)
        contour.clean()

        length = contour.length()
        density= length/contour.N()
        if verbose:
            utils.printc('tomesh():\n\tline length =', length)
            utils.printc('\tdensity =', density, 'length/pt_separation')

        x0,x1 = contour.xbounds()
        y0,y1 = contour.ybounds()

        if grid is None:
            if resMesh is None:
                resx = int((x1-x0)/density+0.5)
                resy = int((y1-y0)/density+0.5)
                if verbose:
                    utils.printc('\tresMesh =', [resx, resy])
            else:
                if utils.isSequence(resMesh):
                    resx, resy = resMesh
                else:
                    resx, resy = resMesh, resMesh
            grid = vedo.shapes.Grid([(x0+x1)/2, (y0+y1)/2, 0],
                                    sx=(x1-x0)*1.025, sy=(y1-y0)*1.025,
                                    resx=resx, resy=resy)
        else:
            grid = grid.clone()


        cpts = contour.points()

        # make sure it's closed
        p0,p1 = cpts[0], cpts[-1]
        nj = max(2, int(utils.mag(p1-p0)/density+0.5))
        joinline = vedo.shapes.Line(p1, p0, res=nj)
        contour = vedo.merge(contour, joinline).clean(0.0001)

        ####################################### quads
        if quads:
            cmesh = grid.clone().cutWithPointLoop(contour, on='cells', invert=invert)
            return cmesh.wireframe(False).lw(0.5)
        #############################################

        grid_tmp = grid.points()

        if jitter:
            np.random.seed(0)
            sigma = 1.0/np.sqrt(grid.N())*grid.diagonalSize()*jitter
            if verbose:
                utils.printc('\tsigma jittering =', sigma)
            grid_tmp += np.random.rand(grid.N(),3) * sigma
            grid_tmp[:,2] = 0.0

        todel = []
        density /= np.sqrt(3)
        vgrid_tmp = Points(grid_tmp)

        for p in contour.points():
            todel += vgrid_tmp.closestPoint(p, radius=density, returnPointId=True)
        # cpoints = contour.points()
        # for i, p in enumerate(cpoints):
        #     if i:
        #         den = utils.mag(p-cpoints[i-1])/1.732
        #     else:
        #         den = density
        #     todel += vgrid_tmp.closestPoint(p, radius=den, returnPointId=True)

        grid_tmp = grid_tmp.tolist()
        for index in sorted(list(set(todel)), reverse=True):
            del grid_tmp[index]

        points = contour.points().tolist() + grid_tmp
        if invert:
            boundary = reversed(range(contour.N()))
        else:
            boundary = range(contour.N())
        if verbose:
            utils.printc('\tperforming Delaunay triangulation..')
        dln = delaunay2D(points, mode='xy', boundaries=[boundary])
        dln.computeNormals(points=False)  # fixes reversd faces
        dln.lw(0.5)
        return dln


    def to_trimesh(self):
        """Return the trimesh object."""
        return utils.vedo2trimesh(self)

    def to_meshlab(self):
        """Return the ``pymeshlab.Mesh`` object."""
        return utils.vedo2meshlab(self)


    def density(self, dims=(40,40,40),
                bounds=None, radius=None,
                computeGradient=False, locator=None):
        """
        Generate a density field from a point cloud. Input can also be a set of 3D coordinates.
        Output is a ``Volume``.
        The local neighborhood is specified as the `radius` around each sample position (each voxel).
        The density is expressed as the number of counts in the radius search.

        :param int,list dims: numer of voxels in x, y and z of the output Volume.

        :param bool computeGradient: Turn on/off the generation of the gradient vector,
            gradient magnitude scalar, and function classification scalar.
            By default this is off. Note that this will increase execution time
            and the size of the output. (The names of these point data arrays are:
            "Gradient", "Gradient Magnitude", and "Classification".)

        :param vtkStaticPointLocator locator: can be assigned from a previous call for speed.

        See example script:

        |plot_density3d| |plot_density3d.py|_
        """
        pdf = vtk.vtkPointDensityFilter()

        poly = self.polydata()
        b = list(poly.GetBounds())
        diag = self.diagonalSize()

        if not utils.isSequence(dims):
            dims = [dims,dims,dims]

        if b[5]-b[4] == 0 or len(dims) == 2: # its 2D
            dims = list(dims)
            dims = [dims[0],dims[1], 2]
            b[5] = b[4] + diag/1000

        pdf.SetInputData(poly)
        pdf.SetSampleDimensions(dims)
        pdf.SetDensityEstimateToFixedRadius()
        pdf.SetDensityFormToNumberOfPoints()
        if locator:
            pdf.SetLocator(locator)
        if radius is None:
            radius = diag/15
        pdf.SetRadius(radius)
        if bounds is None:
            bounds = b
        pdf.SetModelBounds(bounds)
        pdf.SetComputeGradient(computeGradient)
        pdf.Update()
        img = pdf.GetOutput()
        vol = vedo.volume.Volume(img).mode(1)
        vol.name = "PointDensity"
        vol.info['radius'] = radius
        vol.locator = pdf.GetLocator()
        return vol


    def densify(self, targetDistance=0.1, closest=6, radius=None, niter=1, maxN=None):
        """
        Return a copy of the cloud with new added points.
        The new points are created in such a way that all points in any local neighborhood are
        within a target distance of one another.

        For each input point, the distance to all points in its neighborhood is computed.
        If any of its neighbors is further than the target distance,
        the edge connecting the point and its neighbor is bisected and
        a new point is inserted at the bisection point.
        A single pass is completed once all the input points are visited.
        Then the process repeats to the number of iterations.

        .. note:: Points will be created in an iterative fashion until all points in their
            local neighborhood are the target distance apart or less.
            Note that the process may terminate early due to the
            number of iterations. By default the target distance is set to 0.5.
            Note that the targetDistance should be less than the radius
            or nothing will change on output.

        .. warning:: This class can generate a lot of points very quickly.
            The maximum number of iterations is by default set to =1.0 for this reason.
            Increase the number of iterations very carefully.
            Also, `maxN` can be set to limit the explosion of points.
            It is also recommended that a N closest neighborhood is used.
        """
        src = vtk.vtkProgrammableSource()
        opts = self.points()
        def _readPoints():
            output = src.GetPolyDataOutput()
            points = vtk.vtkPoints()
            for p in opts:
                points.InsertNextPoint(p)
            output.SetPoints(points)
        src.SetExecuteMethod(_readPoints)

        dens = vtk.vtkDensifyPointCloudFilter()
        # dens.SetInputData(self.polydata()) # this doesnt work (?)
        dens.SetInputConnection(src.GetOutputPort())
        dens.InterpolateAttributeDataOn()
        dens.SetTargetDistance(targetDistance)
        dens.SetMaximumNumberOfIterations(niter)
        if maxN: dens.SetMaximumNumberOfPoints(maxN)

        if radius:
            dens.SetNeighborhoodTypeToRadius()
            dens.SetRadius(radius)
        elif closest:
            dens.SetNeighborhoodTypeToNClosest()
            dens.SetNumberOfClosestPoints(closest)
        else:
            colors.printc("Error in densifyCloud: set either radius or closestN", c='r')
            raise RuntimeError()
        dens.Update()
        pts = utils.vtk2numpy(dens.GetOutput().GetPoints().GetData())
        cld = Points(pts, c=None).pointSize(self.GetProperty().GetPointSize())
        cld.interpolateDataFrom(self, N=closest, radius=radius)
        cld.name = "densifiedCloud"
        return cld


