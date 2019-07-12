from fireworks import Firework, Workflow
from atomate.vasp.fireworks.core import OptimizeFW
from atomate.vasp.config import VASP_CMD, DB_FILE
from atomate.vasp.powerups import use_custodian
from custodian.vasp.handlers import (
    VaspErrorHandler,
    MeshSymmetryErrorHandler,
    PotimErrorHandler,
    FrozenJobErrorHandler,
    NonConvergingErrorHandler,
    PositiveEnergyErrorHandler,
    StdErrHandler,
)
from uuid import uuid4

from atomate.vasp.fireworks.approx_neb import (
    HostLatticeFW,
    InsertSitesFW,
    ApproxNEBLaunchFW,
    PathFinderFW,
    GetImagesFW,
)

# TODO: Write approx_neb_wf_description
def approx_neb_wf(
    structure,
    working_ion,
    insert_coords,
    n_images,
    vasp_input_set=None,
    override_default_vasp_params=None,
    selective_dynamics_scheme="fix_two_atoms",
    vasp_cmd=VASP_CMD,
    db_file=DB_FILE,
    name="Approx NEB",
):
    approx_neb_params = override_default_vasp_params or {
        "user_incar_settings": {
            "EDIFF": 0.0005,
            "EDIFFG": -0.05,
            "IBRION": 1,
            "ISIF": 3,
            "ISMEAR": 0,
            "LDAU": False,
            "NSW": 200,
            "ADDGRID": True,
            "ISYM": 1,
            "NELMIN": 4,
        }
    }
    # TODO: Add LASPH: True

    wf_uuid = str(uuid4())

    host_lattice_fw = HostLatticeFW(
        structure=structure,
        approx_neb_wf_uuid=wf_uuid,
        db_file=db_file,
        vasp_input_set=vasp_input_set,
        vasp_cmd=vasp_cmd,
        override_default_vasp_params=approx_neb_params.copy(),
    )

    if "user_incar_settings" not in approx_neb_params.keys():
        approx_neb_params = {"user_incar_settings": {}}
    approx_neb_params["user_incar_settings"]["ISIF"] = 2
    approx_neb_params["user_incar_settings"]["ISYM"] = 0

    insert_working_ion_fws = []
    for coord in insert_coords:
        insert_working_ion_fws.append(
            InsertSitesFW(
                approx_neb_wf_uuid=wf_uuid,
                insert_specie=working_ion,
                insert_coords=coord,
                db_file=db_file,
                parents=host_lattice_fw,
            )
        )

    stable_site_fws = []
    for fw in insert_working_ion_fws:
        stable_site_fws.append(
            ApproxNEBLaunchFW(
                calc_type="stable_site",
                approx_neb_wf_uuid=wf_uuid,
                db_file=db_file,
                override_default_vasp_params=approx_neb_params,
                parents=fw,
            )
        )

    pathfinder_fw = PathFinderFW(
        approx_neb_wf_uuid=wf_uuid,
        n_images=n_images,
        db_file=db_file,
        parents=stable_site_fws,
    )

    get_images_fw = GetImagesFW(
        approx_neb_wf_uuid=wf_uuid,
        mobile_specie=working_ion,
        selective_dynamics_scheme=selective_dynamics_scheme,
    )

    relax_image_fws = []
    for n in n_images:
        path = "images.input_structure." + str(n)
        relax_image_fws.append(
            ApproxNEBLaunchFW(
                calc_type="image",
                approx_neb_wf_uuid=wf_uuid,
                structure_path=path,
                db_file=db_file,
                override_default_vasp_params=approx_neb_params,
                parents=get_images_fw,
            )
        )

    wf = Workflow(
        [host_lattice_fw]
        + insert_working_ion_fws
        + stable_site_fws
        + [pathfinder_fw]
        + [get_images_fw]
        + relax_image_fws
    )

    wf = use_custodian(
        wf,
        custodian_params={
            "handler_group": [
                VaspErrorHandler(),
                MeshSymmetryErrorHandler(),
                NonConvergingErrorHandler(),
                PotimErrorHandler(),
                PositiveEnergyErrorHandler(),
                FrozenJobErrorHandler(),
                StdErrHandler(),
            ]
        },
    )
    wf.name = name

    return wf
