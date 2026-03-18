"""Re-export stub — moved to facade_doctor.py."""
from trcc.adapters.infra.facade_doctor import *  # noqa: F401,F403
from trcc.adapters.infra.facade_doctor import (  # noqa: F401
    _check_binary,
    _check_gpu_packages,
    _check_library,
    _check_python_module,
    _check_rapl_permissions,
    _check_udev_rules,
    _detect_pkg_manager,
    _install_hint,
    _provides_search,
    _read_os_release,
)
