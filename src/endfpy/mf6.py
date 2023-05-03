from typing import TextIO

import numpy as np

from .records import get_tab2_record, get_list_record, get_head_record, \
    get_tab1_record, get_cont_record


def parse_mf6(file_obj: TextIO) -> dict:
    """Generate products from MF=6 in an ENDF evaluation

    Parameters
    ----------
    ev : openmc.data.endf.Evaluation
        ENDF evaluation to read from
    mt : int
        The MT value of the reaction to get products for

    Raises
    ------
    IOError
        When the Kalbach-Mann systematics is used, but the product
        is not defined in the 'center-of-mass' system. The breakup logic
        is not implemented which can lead to this error being raised while
        the definition of the product is correct.

    Returns
    -------
    products : list of openmc.data.Product
        Products of the reaction

    """
    # Read HEAD record
    ZA, AWR, JP, LCT, NK, _ = get_head_record(file_obj)
    data = {'ZA': ZA, 'AWR': AWR, 'JP': JP, 'LCT': LCT, 'NK': NK}

    data['products'] = products = []
    for i in range(NK):
        # Get yield for this product
        (ZAP, AWP, LIP, LAW), y_i = get_tab1_record(file_obj)
        ZAP = int(ZAP)

        p = {'ZAP': ZAP, 'AWP': AWP, 'LIP': LIP, 'LAW': LAW, 'y_i': y_i}

        if LAW < 0:
            # Distribution given elsewhere
            pass
        elif LAW == 0:
            # No distribution given
            pass
        elif LAW == 1:
            # Continuum energy-angle distribution
            p['distribution'] = ContinuumEnergyAngle.dict_from_endf(file_obj)

        elif LAW == 2:
            # Discrete two-body scattering
            p['distribution'] = DiscreteTwoBodyScattering.dict_from_endf(file_obj)
        elif LAW == 3:
            # Isotropic discrete emission
            pass

        elif LAW == 4:
            # Discrete two-body recoil
            pass

        elif LAW == 5:
            # Charged particle elastic scattering
            p['distribution'] = ChargedParticleElasticScattering.dict_from_endf(file_obj)

        elif LAW == 6:
            # N-body phase-space distribution
            p['distribution'] = NBodyPhaseSpace.dict_from_endf(file_obj)

        elif LAW == 7:
            # Laboratory energy-angle distribution
            p['distribution'] = LaboratoryAngleEnergy.dict_from_endf(file_obj)

        products.append(p)

    return data


class ContinuumEnergyAngle:
    def __init__(self):
        pass

    @staticmethod
    def dict_from_endf(file_obj: TextIO) -> dict:
        params, E_int = get_tab2_record(file_obj)
        _, _, LANG, LEP, NR, NE = params

        data = {'LANG': LANG, 'LEP': LEP, 'NR': NR, 'NE': NE, 'E_int': E_int}

        data['E'] = np.zeros(NE)
        data['distribution'] = []
        for i in range(NE):
            items, values = get_list_record(file_obj)
            _, E_i, ND, NA, NW, NEP = items
            dist = {'ND': ND, 'NA': NA, 'NW': NW, 'NEP': NEP}
            data['E'][i] = E_i
            values = np.asarray(values)
            values.shape = (NEP, NA + 2)
            dist["E'"] = values[:, 0]
            dist['b'] = values[:, 1:]
            data['distribution'].append(dist)

        return data


class DiscreteTwoBodyScattering:
    def __init__(self):
        pass

    @staticmethod
    def dict_from_endf(file_obj: TextIO) -> dict:
        params, E_int = get_tab2_record(file_obj)
        *_, NR, NE = params
        data = {'NR': NR, 'NE': NE, 'E_int': E_int}

        data['E'] = np.zeros(NE)
        data['distribution'] = []
        for i in range(NE):
            items, values = get_list_record(file_obj)
            _, E_i, LANG, _, NW, NL = items
            dist = {'LANG': LANG, 'NW': NW, 'NL': NL}
            data['E'][i] = E_i
            data['A_l'] = np.asarray(values)
            data['distribution'].append(dist)


class ChargedParticleElasticScattering:
    def __init__(self):
        pass

    @staticmethod
    def dict_from_endf(file_obj: TextIO) -> dict:
        return {}


class NBodyPhaseSpace:
    def __init__(self):
        pass

    @staticmethod
    def dict_from_endf(file_obj: TextIO) -> dict:
        APSX, *_, NPSX = get_cont_record(file_obj)
        return {'APSX': APSX, 'NPSX': NPSX}


class LaboratoryAngleEnergy:
    def __init__(self):
        pass

    @staticmethod
    def dict_from_endf(file_obj: TextIO) -> dict:
        return {}