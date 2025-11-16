""" Provides the classes and components for the ui interface """

# DGT Centaur display control functions
#
# This file is part of the DGTCentaur Mods open source software
# ( https://github.com/EdNekebno/DGTCentaur )
#
# DGTCentaur Mods is free software: you can redistribute
# it and/or modify it under the terms of the GNU General Public
# License as published by the Free Software Foundation, either
# version 3 of the License, or (at your option) any later version.
#
# DGTCentaur Mods is distributed in the hope that it will
# be useful, but WITHOUT ANY WARRANTY; without even the implied warranty
# of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this file.  If not, see
#
# https://github.com/EdNekebno/DGTCentaur/blob/master/LICENSE.md
#
# This and any other notices must remain intact and unaltered in any
# distribution, modification, variant, or derivative of this software.

import os
from typing import Final

RESOURCE_ENV: Final[str] = "DGTCM_RESOURCES"

class AssetManager():
    """Helper class for resolving resource paths used by display widgets."""

    @staticmethod
    def get_resource_path(resource_file):
        """ Return resource path from the resources folder or /home/pi/resources """

        if resource_file.find("..") >= 0:
            return ""

        search_paths = []

        custom_root = os.environ.get(RESOURCE_ENV)
        if custom_root:
            search_paths.append(custom_root)

        search_paths.extend(("/home/pi/resources", "/opt/DGTCentaurMods/resources"))

        for base in search_paths:
            candidate = os.path.join(base, resource_file)
            if os.path.exists(candidate):
                return candidate

        # Default back to the Centaur install path to maintain legacy behavior.
        return os.path.join("/opt/DGTCentaurMods/resources", resource_file)
        