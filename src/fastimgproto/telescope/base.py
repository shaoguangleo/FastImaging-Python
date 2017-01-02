from __future__ import print_function

from itertools import combinations

import astropy.io.ascii as ascii
import astropy.units as u
import attr.validators
import numpy as np
from astropy.coordinates import (Latitude, Longitude, EarthLocation, )
from astropy.table import Table
from attr import attrib, attrs

from fastimgproto.coord_transforms import (
    xyz_to_uvw_rotation_matrix,
    z_rotation_matrix
)

_validator_optional_ndarray = attr.validators.optional(
    attr.validators.instance_of(np.ndarray))


@attrs
class Telescope(object):
    """
    Data-structure for holding together array layout and central position.

    Also takes care of baseline calculation and antenna/baseline label-tracking.

    Instantiate using the named constructors, e.g.::

        meerkat = Telescope.from_itrf(
            *parse_itrf_ascii_to_xyz_and_labels(meerkat_itrf_filepath)
        )

    Attributes:
        latitude (astropy.coordinates.Latitude): Latitude of array
        longitude (astropy.coordinates.Longitude): Longitude of array
        ant_labels (list): Antennae labels
        ant_itrf_xyz (numpy.ndarray): Antennae xyz_positions in ITRF frame.
            [dtype: ``np.float_``, shape ``(n_antennae,3,)``.
        ant_local_xyz (numpy.ndarray): Antennae xyz_positions in local-XYZ frame.
            [dtype: ``np.float_``, shape ``(n_antennae,3,)``.
        baseline_local_xyz (numpy.ndarray): Baseline xyz-vectors in local-XYZ frame.
            [dtype: ``np.float_``, shape ``(n_baselines,3,)``.
        baseline_labels (list): Baseline labels.
            (See also :func:`generate_baselines_and_labels`)
    """
    latitude = attrib(validator=attr.validators.instance_of(Latitude))
    longitude = attrib(validator=attr.validators.instance_of(Longitude))
    ant_labels = attrib(default=None)
    ant_itrf_xyz = attrib(default=None, validator=_validator_optional_ndarray)
    ant_local_xyz = attrib(default=None, validator=_validator_optional_ndarray)
    baseline_local_xyz = attrib(init=False)
    baseline_labels = attrib(init=False)

    def __attrs_post_init__(self):
        """
        Generate the baselines and baseline-labels
        """
        self.baseline_local_xyz, self.baseline_labels = generate_baselines_and_labels(
            self.ant_local_xyz, self.ant_labels
        )

    @staticmethod
    def from_itrf(ant_itrf_xyz, ant_labels):
        """
        Instantiate telescope model from ITRF co-ordinates of antennae

        (aka ECEF-coords, i.e. Earth-Centered-Earth-Fixed reference frame.)

        Takes care of calculating central Latitude and Longitude from the mean
        antenna position, and converts the antenna positions into local-XYZ
        frame.

        Args:
            ant_itrf_xyz (numpy.ndarray): Array co-ordinatates in the ITRF frame
            ant_labels (list): Antennae labels
        Returns:
            Telescope: A telescope class with the given array co-ords.
        """
        mean_posn = np.mean(ant_itrf_xyz, axis=0)
        lon, lat, alt = EarthLocation.from_geocentric(mean_posn[0],
                                                      mean_posn[1],
                                                      mean_posn[2],
                                                      unit=u.m,
                                                      ).to_geodetic()

        mean_subbed_itrf = ant_itrf_xyz - mean_posn

        rotation = z_rotation_matrix(lon)
        ant_local_xyz = np.dot(rotation, mean_subbed_itrf.T).T

        return Telescope(
            latitude=lat,
            longitude=lon,
            ant_labels=ant_labels,
            ant_itrf_xyz=ant_itrf_xyz,
            ant_local_xyz=ant_local_xyz,
        )

    def uvw_at_local_hour_angle(self, local_hour_angle, dec):
        """
        Transform baselines to UVW for source at given local-hour-angle and Dec.

        Args:
            local_hour_angle (astropy.units.Quantity): Local hour angle.
                LHA=0 is transit, LHA=-6h is rising, LHA=+6h is setting.
                [Dimensions of angular width / arc, e.g.
                ``u.deg``, ``u.rad``, or ``u.hourangle``]
            dec (astropy.units.Quantity): Declination.
                [Dimensions of angular width / arc]

        Returns:
            astropy.units.Quantity: UVW-array, with units of metres.
            [Shape: ``(3, n_baselines)``, dtype: ``numpy.float_``].
        """
        rotation = xyz_to_uvw_rotation_matrix(local_hour_angle, dec)
        return np.dot(rotation, self.baseline_local_xyz.T).T

    def uvw_at_skycoord_and_time(self, pointing_centre, utc_time):
        pass


def generate_baselines_and_labels(antenna_positions, antenna_labels):
    """
    Given an array of antenna positions, generate an array of baseline-vectors.

    Baseline-vectors are generated as follows:

    - It is assumed that the antenna-positions supplied are already in the
      desired order, with matching labels in the antenna_labels list.
      (Typically something like ``['ANT1','ANT2','ANT3']``.

    - Pairings are then generated according to position in the supplied list,
      as follows::

          pairings = list(itertools.combinations(range(len(antenna_positions)), 2))

    - Baseline labels are concatenated with a comma, e.g.
      pairing of ``'ANT1'`` and ``'ANT2'`` has label ``'ANT1,ANT2'``.
    - Baseline vectors represent translation **from** first antenna **to**
      second antenna, therefore::

          baseline_1_2 = ant_2_pos - ant_1_pos


    Args:
        antenna_positions (numpy.ndarray): Antennae xyz_positions in local-XYZ frame.
            [dtype: ``np.float_``, shape ``(n_antennae,3,)``.
        antenna_labels (list): Antennae labels

    Returns:
        tuple: ``(baseline_vecs, baseline_labels)``. Both of length
        :math:`n_{baselines} = {n_{antennae}  \choose 2}`,
        where ``baseline_labels`` is simply a
        list of strings, and
        ``baseline_vecs`` is  a (numpy.ndarray)
        [dtype: ``np.float_``, shape ``(n_baselines,3,)``.
    """
    assert len(antenna_positions) == len(antenna_labels)
    # Check that the antenna labels are unique:
    assert len(set(antenna_labels)) == len(antenna_labels)
    pairings = list(combinations(range(len(antenna_positions)), 2))
    n_baselines = len(pairings)
    baseline_vecs = np.zeros((n_baselines, 3), dtype=np.float_)
    baseline_labels = [None] * n_baselines
    for baseline_idx, pair in enumerate(pairings):
        ant_1_idx, ant_2_idx = pair
        baseline_labels[baseline_idx] = ','.join(
            (antenna_labels[ant_1_idx], antenna_labels[ant_2_idx]))
        baseline_vecs[baseline_idx] = (
            antenna_positions[ant_2_idx] - antenna_positions[ant_1_idx]
        )

    return baseline_vecs, baseline_labels


def hstack_table_columns_as_ndarray(cols):
    """
    When passed a subset of astropy Table columns, turn them into a 2-d ndarray.

    (Note, columns should have same dtype)

    Example:
        >>> import numpy as np
        >>> import astropy.table
        >>> x = np.arange(5)
        >>> y = x**2
        >>> t = astropy.table.Table(data=(x,y), names=('x','y'))
        >>> hstack_table_columns_as_ndarray(t.columns[:2])
        array([[ 0,  0],
               [ 1,  1],
               [ 2,  4],
               [ 3,  9],
               [ 4, 16]])

    Args:
        cols (list): List (or iterable) of :class:`astropy.table.TableColumns`.
            Typically a table or a slice of a table's columns.

    Returns:
        numpy.ndarray: H-stacked columns-array.
    """
    tmp_tbl = Table(cols)
    return np.hstack(tmp_tbl[cname].reshape(-1, 1)
                     for cname in tmp_tbl.colnames)


def parse_itrf_ascii_to_xyz_and_labels(tabledata):
    """
    Read ITRF data in ascii format and return (antenna positions, labels).

    ASCII table should be simple whitespace-delimited, column order:
    ``x y z diameter label mount``

    Args:
        tabledata: (str, file-like, or list).
            File-object or path-to-file.

    Returns:
        tuple: Tuple of ``(ant_itrf_xyz, ant_labels)``, where ``ant_itrf_xyz``
        is a `numpy.ndarray` of shape ``(n,3)``, dtype ``np.float_`` and
        ant_labels is a `numpy.ndarray` of shape ``(n,)``, dtype ``np.str_``.
    """
    tbl = ascii.read(tabledata,
                     names=('x', 'y', 'z', 'diameter', 'label', 'mount'))
    xyz = hstack_table_columns_as_ndarray(tbl.columns[:3]) * u.m
    labels = tbl['label'].data
    return xyz, labels