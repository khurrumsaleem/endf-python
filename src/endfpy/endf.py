"""Module for parsing and manipulating data from ENDF evaluations.

All the classes and functions in this module are based on document
ENDF-102 titled "Data Formats and Procedures for the Evaluated Nuclear
Data File ENDF-6". The latest version from June 2009 can be found at
http://www-nds.iaea.org/ndspub/documents/endf/endf102/endf102.pdf

"""
import io
from pathlib import PurePath
from warnings import warn

import numpy as np

from .data import gnds_name
from .energy_distribution import ArbitraryTabulated, GeneralEvaporation, \
    MaxwellEnergy, Evaporation,  WattEnergy, MadlandNix
from .records import get_head_record, get_text_record, get_cont_record, \
    get_tab1_record, get_list_record, get_tab2_record


_LIBRARY = {0: 'ENDF/B', 1: 'ENDF/A', 2: 'JEFF', 3: 'EFF',
            4: 'ENDF/B High Energy', 5: 'CENDL', 6: 'JENDL',
            17: 'TENDL', 18: 'ROSFOND', 21: 'SG-21', 31: 'INDL/V',
            32: 'INDL/A', 33: 'FENDL', 34: 'IRDF', 35: 'BROND',
            36: 'INGDB-90', 37: 'FENDL/A', 41: 'BROND'}

_SUBLIBRARY = {
    0: 'Photo-nuclear data',
    1: 'Photo-induced fission product yields',
    3: 'Photo-atomic data',
    4: 'Radioactive decay data',
    5: 'Spontaneous fission product yields',
    6: 'Atomic relaxation data',
    10: 'Incident-neutron data',
    11: 'Neutron-induced fission product yields',
    12: 'Thermal neutron scattering data',
    19: 'Neutron standards',
    113: 'Electro-atomic data',
    10010: 'Incident-proton data',
    10011: 'Proton-induced fission product yields',
    10020: 'Incident-deuteron data',
    10030: 'Incident-triton data',
    20030: 'Incident-helion (3He) data',
    20040: 'Incident-alpha data'
}

SUM_RULES = {1: [2, 3],
             3: [4, 5, 11, 16, 17, 22, 23, 24, 25, 27, 28, 29, 30, 32, 33, 34, 35,
                 36, 37, 41, 42, 44, 45, 152, 153, 154, 156, 157, 158, 159, 160,
                 161, 162, 163, 164, 165, 166, 167, 168, 169, 170, 171, 172,
                 173, 174, 175, 176, 177, 178, 179, 180, 181, 183, 184, 185,
                 186, 187, 188, 189, 190, 194, 195, 196, 198, 199, 200],
             4: list(range(50, 92)),
             16: list(range(875, 892)),
             18: [19, 20, 21, 38],
             27: [18, 101],
             101: [102, 103, 104, 105, 106, 107, 108, 109, 111, 112, 113, 114,
                   115, 116, 117, 155, 182, 191, 192, 193, 197],
             103: list(range(600, 650)),
             104: list(range(650, 700)),
             105: list(range(700, 750)),
             106: list(range(750, 800)),
             107: list(range(800, 850))}


def get_evaluations(filename):
    """Return a list of all evaluations within an ENDF file.

    Parameters
    ----------
    filename : str
        Path to ENDF-6 formatted file

    Returns
    -------
    list
        A list of :class:`openmc.data.endf.Evaluation` instances.

    """
    evaluations = []
    with open(str(filename), 'r') as fh:
        while True:
            pos = fh.tell()
            line = fh.readline()
            if line[66:70] == '  -1':
                break
            fh.seek(pos)
            evaluations.append(Evaluation(fh))
    return evaluations


class Evaluation:
    """ENDF material evaluation with multiple files/sections

    Parameters
    ----------
    filename_or_obj : str or file-like
        Path to ENDF file to read or an open file positioned at the start of an
        ENDF material

    Attributes
    ----------
    info : dict
        Miscellaneous information about the evaluation.
    target : dict
        Information about the target material, such as its mass, isomeric state,
        whether it's stable, and whether it's fissionable.
    projectile : dict
        Information about the projectile such as its mass.
    reaction_list : list of 4-tuples
        List of sections in the evaluation. The entries of the tuples are the
        file (MF), section (MT), number of records (NC), and modification
        indicator (MOD).
    section : dict
        Dictionary mapping (MF, MT) to corresponding section of the ENDF file.

    """
    def __init__(self, filename_or_obj):
        if isinstance(filename_or_obj, (str, PurePath)):
            fh = open(str(filename_or_obj), 'r')
            need_to_close = True
        else:
            fh = filename_or_obj
            need_to_close = False
        self.section = {}
        self.info = {}
        self.target = {}
        self.projectile = {}
        self.reaction_list = []

        # Skip TPID record. Evaluators sometimes put in TPID records that are
        # ill-formated because they lack MF/MT values or put them in the wrong
        # columns.
        if fh.tell() == 0:
            fh.readline()
        MF = 0

        # Determine MAT number for this evaluation
        while MF == 0:
            position = fh.tell()
            line = fh.readline()
            MF = int(line[70:72])
        self.material = int(line[66:70])
        fh.seek(position)

        while True:
            # Find next section
            while True:
                position = fh.tell()
                line = fh.readline()
                MAT = int(line[66:70])
                MF = int(line[70:72])
                MT = int(line[72:75])
                if MT > 0 or MAT == 0:
                    fh.seek(position)
                    break

            # If end of material reached, exit loop
            if MAT == 0:
                fh.readline()
                break

            section_data = ''
            while True:
                line = fh.readline()
                if line[72:75] == '  0':
                    break
                else:
                    section_data += line
            self.section[MF, MT] = section_data

        if need_to_close:
            fh.close()

        self._read_mf1_mt451()
        self._read_mf3()
        self._read_mf4()
        self._read_mf5()

    def __repr__(self):
        name = self.target['zsymam'].replace(' ', '')
        return '<{} for {} {}>'.format(self.info['sublibrary'], name,
                                       self.info['library'])

    def _read_mf1_mt451(self):
        file_obj = io.StringIO(self.section[1, 451])

        # Information about target/projectile
        items = get_head_record(file_obj)
        Z, A = divmod(items[0], 1000)
        self.target['atomic_number'] = Z
        self.target['mass_number'] = A
        self.target['mass'] = items[1]
        self._LRP = items[2]
        self.target['fissionable'] = (items[3] == 1)
        try:
            library = _LIBRARY[items[4]]
        except KeyError:
            library = 'Unknown'
        self.info['modification'] = items[5]

        # Control record 1
        items = get_cont_record(file_obj)
        self.target['excitation_energy'] = items[0]
        self.target['stable'] = (int(items[1]) == 0)
        self.target['state'] = items[2]
        self.target['isomeric_state'] = m = items[3]
        self.info['format'] = items[5]
        assert self.info['format'] == 6

        # Set correct excited state for Am242_m1, which is wrong in ENDF/B-VII.1
        if Z == 95 and A == 242 and m == 1:
            self.target['state'] = 2

        # Control record 2
        items = get_cont_record(file_obj)
        self.projectile['mass'] = items[0]
        self.info['energy_max'] = items[1]
        library_release = items[2]
        self.info['sublibrary'] = _SUBLIBRARY[items[4]]
        library_version = items[5]
        self.info['library'] = (library, library_version, library_release)

        # Control record 3
        items = get_cont_record(file_obj)
        self.target['temperature'] = items[0]
        self.info['derived'] = (items[2] > 0)
        NWD = items[4]
        NXC = items[5]

        # Text records
        text = [get_text_record(file_obj) for i in range(NWD)]
        if len(text) >= 5:
            self.target['zsymam'] = text[0][0:11]
            self.info['laboratory'] = text[0][11:22]
            self.info['date'] = text[0][22:32]
            self.info['author'] = text[0][32:66]
            self.info['reference'] = text[1][1:22]
            self.info['date_distribution'] = text[1][22:32]
            self.info['date_release'] = text[1][33:43]
            self.info['date_entry'] = text[1][55:63]
            self.info['identifier'] = text[2:5]
            self.info['description'] = text[5:]
        else:
            self.target['zsymam'] = 'Unknown'

        # File numbers, reaction designations, and number of records
        for i in range(NXC):
            _, _, mf, mt, nc, mod = get_cont_record(file_obj, skip_c=True)
            self.reaction_list.append((mf, mt, nc, mod))

    def _read_mf3(self):
        # Generate cross section
        self.cross_sections = {}
        for (mf, mt), text in self.section.items():
            if mf != 3:
                continue

            file_obj = io.StringIO(text)
            get_head_record(file_obj)
            params, xs = get_tab1_record(file_obj)
            self.cross_sections[mt] = {
                'QM': params[0],
                'QI': params[1],
                'LR': params[3],
                'sigma': xs
            }

    def _read_mf4(self):
        self.angular_distributions = {}
        for (mf, mt), text in self.section.items():
            if mf != 4:
                continue

            file_obj = io.StringIO(text)

            # Read HEAD record
            items = get_head_record(file_obj)
            LVT = items[2]
            LTT = items[3]

            # Read CONT record
            items = get_cont_record(file_obj)
            LI = items[2]
            LCT = items[3]
            NK = items[4]

            self.angular_distributions[mt] = data = {
                'LTT': LTT,
                'LI': LI,
                'LCT': LCT,
            }

            # Check for obsolete energy transformation matrix. If present, just skip
            # it and keep reading
            if LVT > 0:
                warn('Obsolete energy transformation matrix in MF=4 angular '
                     'distribution.')
                for _ in range((NK + 5)//6):
                    file_obj.readline()

            def legendre_data(file_obj):
                data = {}
                params, data['E_int'] = get_tab2_record(file_obj)
                n_energy = params[5]

                energy = np.zeros(n_energy)
                a_l = []
                for i in range(n_energy):
                    items, al = get_list_record(file_obj)
                    data['T'] = items[0]
                    energy[i] = items[1]
                    data['LT'] = items[2]
                    coefficients = np.array(al)
                    a_l.append(coefficients)
                data['a_l'] = a_l
                data['E'] = energy
                return data

            def tabulated_data(file_obj):
                data = {}
                params, data['E_int'] = get_tab2_record(file_obj)
                n_energy = params[5]

                energy = np.zeros(n_energy)
                mu = []
                for i in range(n_energy):
                    params, f = get_tab1_record(file_obj)
                    data['T'] = params[0]
                    energy[i] = params[1]
                    data['LT'] = params[2]
                    mu.append(f)
                data['E'] = energy
                data['mu'] = mu
                return data

            if LTT == 0 and LI == 1:
                # Purely isotropic
                pass

            elif LTT == 1 and LI == 0:
                # Legendre polynomial coefficients
                data['legendre'] = legendre_data(file_obj)

            elif LTT == 2 and LI == 0:
                # Tabulated probability distribution
                data['tabulated'] = tabulated_data(file_obj)

            elif LTT == 3 and LI == 0:
                # Legendre for low energies / tabulated for high energies
                data['legendre'] = legendre_data(file_obj)
                data['tabulated'] = tabulated_data(file_obj)

    def _read_mf5(self):
        self.energy_distributions = {}
        for (mf, mt), text in self.section.items():
            if mf != 5:
                continue

            file_obj = io.StringIO(self.section[5, mt])
            items = get_head_record(file_obj)
            NK = items[4]

            self.energy_distributions[mt] = data = {'NK': NK}
            data['subsections'] = []
            for _ in range(NK):
                subsection = {}
                params, applicability = get_tab1_record(file_obj)
                subsection['LF'] = LF = params[3]
                subsection['p'] = applicability
                if LF == 1:
                    dist = ArbitraryTabulated.dict_from_endf(file_obj, params)
                elif LF == 5:
                    return GeneralEvaporation.from_endf(file_obj, params)
                elif LF == 7:
                    return MaxwellEnergy.from_endf(file_obj, params)
                elif LF == 9:
                    return Evaporation.from_endf(file_obj, params)
                elif LF == 11:
                    return WattEnergy.from_endf(file_obj, params)
                elif LF == 12:
                    return MadlandNix.from_endf(file_obj, params)

                subsection['distribution'] = dist
                data['subsections'].append(subsection)

    @property
    def gnds_name(self):
        return gnds_name(self.target['atomic_number'],
                         self.target['mass_number'],
                         self.target['isomeric_state'])
