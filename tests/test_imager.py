import numpy as np
import astropy.units as u

import fastimgproto.gridder.conv_funcs as conv_funcs
from fastimgproto.imager import image_visibilities


def test_normalization():
    n_image = 16  # pixel co-ords -8 through 7.
    support = 3
    uvw_pixel_coords = np.array([
        (-4., 0, 0),
        (3., 0, 0),
        (0., 2.5, 0)
    ])
    # Real vis will be complex_, but we can substitute float_ for testing:
    vis_amplitude = 42.123
    vis = vis_amplitude * np.ones(len(uvw_pixel_coords), dtype=np.float_)
    vis_weights = [1., 1.5, 3. / 4.]
    cell_size = 1 * u.arcsec

    grid_pixel_width_lambda = 1.0 / (cell_size.to(u.rad) * n_image)
    uvw_lambda = uvw_pixel_coords * grid_pixel_width_lambda.value

    image, beam = image_visibilities(vis,
                                     vis_weights=vis_weights,
                                     uvw_lambda=uvw_lambda,
                                     image_size=n_image * u.pix,
                                     cell_size=cell_size,
                                     kernel_func=conv_funcs.Gaussian(trunc=2.5),
                                     kernel_support=3,

                                     )

    assert beam.max() == 1.0
    assert image.max() == vis_amplitude
