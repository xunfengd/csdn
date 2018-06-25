## @file
# Generate PCD table for 'Patchable In Module' type PCD with given .map file.
#    The Patch PCD table like:
#    
#    PCD Name    Offset in binary
#    ========    ================
#
# Copyright (c) 2008 - 2018, Intel Corporation. All rights reserved.<BR>
# This program and the accompanying materials
# are licensed and made available under the terms and conditions of the BSD License
# which accompanies this distribution.  The full text of the license may be found at
# http://opensource.org/licenses/bsd-license.php
#
# THE PROGRAM IS DISTRIBUTED UNDER THE BSD LICENSE ON AN "AS IS" BASIS,
# WITHOUT WARRANTIES OR REPRESENTATIONS OF ANY KIND, EITHER EXPRESS OR IMPLIED.
#
#

#======================================  External Libraries ========================================
from __future__ import print_function
import optparse
import Common.LongFilePathOs as os
import re
import array

from Common.BuildToolError import *
import Common.EdkLogger as EdkLogger
from Common.Misc import PeImageClass, startPatternGeneral, addressPatternGeneral, valuePatternGcc, pcdPatternGcc, secReGeneral
from Common.BuildVersion import gBUILD_VERSION
from Common.LongFilePathSupport import OpenLongFilePath as open

# Version and Copyright
__version_number__ = ("0.10" + " " + gBUILD_VERSION)
__version__ = "%prog Version " + __version_number__
__copyright__ = "Copyright (c) 2008 - 2018, Intel Corporation. All rights reserved."

#======================================  Internal Libraries ========================================

#============================================== Code ===============================================
symRe = re.compile('^([\da-fA-F]+):([\da-fA-F]+) +([\.\-:\\\\\w\?@\$<>]+) +([\da-fA-F]+)', re.UNICODE)

def parsePcdInfoFromMapFile(mapfilepath, efifilepath):
    """ Parse map file to get binary patch pcd information 
    @param path    Map file absolution path
    
    @return a list which element hold (PcdName, Offset, SectionName)
    """
    lines = []
    try:
        f = open(mapfilepath, 'r')
        lines = f.readlines()
        f.close()
    except:
        return None
    
    if len(lines) == 0: return None
    firstline = lines[0].strip()
    if (firstline.startswith("Archive member included ") and
        firstline.endswith(" file (symbol)")):
        return _parseForGCC(lines, efifilepath)
    if firstline.startswith("# Path:"):
        return _parseForXcode(lines, efifilepath)
    return _parseGeneral(lines, efifilepath)

def _parseForXcode(lines, efifilepath):
    valuePattern = re.compile('^([\da-fA-FxX]+)([\s\S]*)([_]*_gPcd_BinaryPatch_([\w]+))')
    status = 0
    pcds = []
    for line in lines:
        line = line.strip()
        if status == 0 and line == "# Symbols:":
            status = 1
            continue
        if status == 1 and len(line) != 0:
            if '_gPcd_BinaryPatch_' in line:
                m = valuePattern.match(line)
                if m is not None:
                    pcds.append((m.groups(0)[3], int(m.groups(0)[0], 16)))
    return pcds

def _parseForGCC(lines, efifilepath):
    """ Parse map file generated by GCC linker """
    dataPattern = re.compile('^.data._gPcd_BinaryPatch_([\w_\d]+)$')
    status = 0
    imageBase = -1
    sections = []
    bpcds = []
    for index, line in enumerate(lines):
        line = line.strip()
        # status machine transection
        if status == 0 and line == "Memory Configuration":
            status = 1
            continue
        elif status == 1 and line == 'Linker script and memory map':
            status = 2
            continue
        elif status ==2 and line == 'START GROUP':
            status = 3
            continue

        # status handler
        if status == 3:
            m = valuePatternGcc.match(line)
            if m is not None:
                sections.append(m.groups(0))
        if status == 3:
            m = dataPattern.match(line)
            if m is not None:
                if lines[index + 1]:
                    PcdName = m.groups(0)[0]
                    m = pcdPatternGcc.match(lines[index + 1].strip())
                    if m is not None:
                        bpcds.append((PcdName, int(m.groups(0)[0], 16) , int(sections[-1][1], 16), sections[-1][0]))
                
    # get section information from efi file
    efisecs = PeImageClass(efifilepath).SectionHeaderList
    if efisecs is None or len(efisecs) == 0:
        return None
    #redirection
    redirection = 0
    for efisec in efisecs:
        for section in sections:
            if section[0].strip() == efisec[0].strip() and section[0].strip() == '.text':
                redirection = int(section[1], 16) - efisec[1]
    pcds = []
    for pcd in bpcds:
        for efisec in efisecs:
            if pcd[1] >= efisec[1] and pcd[1] < efisec[1]+efisec[3]:
                #assert efisec[0].strip() == pcd[3].strip() and efisec[1] + redirection == pcd[2], "There are some differences between map file and efi file"
                pcds.append([pcd[0], efisec[2] + pcd[1] - efisec[1] - redirection, efisec[0]])
    return pcds
                
def _parseGeneral(lines, efifilepath):
    """ For MSFT, ICC, EBC 
    @param lines    line array for map file
    
    @return a list which element hold (PcdName, Offset, SectionName)
    """
    status = 0    #0 - beginning of file; 1 - PE section definition; 2 - symbol table
    secs = []    # key = section name
    bPcds = []
    symPattern = re.compile('^[_]+gPcd_BinaryPatch_([\w]+)')

    for line in lines:
        line = line.strip()
        if startPatternGeneral.match(line):
            status = 1
            continue
        if addressPatternGeneral.match(line):
            status = 2
            continue
        if line.startswith("entry point at"):
            status = 3
            continue
        if status == 1 and len(line) != 0:
            m = secReGeneral.match(line)
            assert m is not None, "Fail to parse the section in map file , line is %s" % line
            sec_no, sec_start, sec_length, sec_name, sec_class = m.groups(0)
            secs.append([int(sec_no, 16), int(sec_start, 16), int(sec_length, 16), sec_name, sec_class])
        if status == 2 and len(line) != 0:
            m = symRe.match(line)
            assert m is not None, "Fail to parse the symbol in map file, line is %s" % line
            sec_no, sym_offset, sym_name, vir_addr = m.groups(0)
            sec_no = int(sec_no, 16)
            sym_offset = int(sym_offset, 16)
            vir_addr = int(vir_addr, 16)
            m2 = symPattern.match(sym_name)
            if m2 is not None:
                # fond a binary pcd entry in map file
                for sec in secs:
                    if sec[0] == sec_no and (sym_offset >= sec[1] and sym_offset < sec[1] + sec[2]):
                        bPcds.append([m2.groups(0)[0], sec[3], sym_offset, vir_addr, sec_no])

    if len(bPcds) == 0: return None

    # get section information from efi file
    efisecs = PeImageClass(efifilepath).SectionHeaderList
    if efisecs is None or len(efisecs) == 0:
        return None
    
    pcds = []
    for pcd in bPcds:
        index = 0
        for efisec in efisecs:
            index = index + 1
            if pcd[1].strip() == efisec[0].strip():
                pcds.append([pcd[0], efisec[2] + pcd[2], efisec[0]])
            elif pcd[4] == index:
                pcds.append([pcd[0], efisec[2] + pcd[2], efisec[0]])
    return pcds
    
def generatePcdTable(list, pcdpath):
    try:
        f = open(pcdpath, 'w')
    except:
        pass

    f.write('PCD Name                       Offset    Section Name\r\n')
    
    for pcditem in list:
        f.write('%-30s 0x%-08X %-6s\r\n' % (pcditem[0], pcditem[1], pcditem[2]))
    f.close()

    #print 'Success to generate Binary Patch PCD table at %s!' % pcdpath 

if __name__ == '__main__':
    UsageString = "%prog -m <MapFile> -e <EfiFile> -o <OutFile>"
    AdditionalNotes = "\nPCD table is generated in file name with .BinaryPcdTable.txt postfix"
    parser = optparse.OptionParser(description=__copyright__, version=__version__, usage=UsageString)
    parser.add_option('-m', '--mapfile', action='store', dest='mapfile',
                      help='Absolute path of module map file.')
    parser.add_option('-e', '--efifile', action='store', dest='efifile',
                      help='Absolute path of EFI binary file.')
    parser.add_option('-o', '--outputfile', action='store', dest='outfile',
                      help='Absolute path of output file to store the got patchable PCD table.')
  
    (options, args) = parser.parse_args()

    if options.mapfile is None or options.efifile is None:
        print(parser.get_usage())
    elif os.path.exists(options.mapfile) and os.path.exists(options.efifile):
        list = parsePcdInfoFromMapFile(options.mapfile, options.efifile)
        if list is not None:
            if options.outfile is not None:
                generatePcdTable(list, options.outfile)
            else:
                generatePcdTable(list, options.mapfile.replace('.map', '.BinaryPcdTable.txt'))
        else:
            print('Fail to generate Patch PCD Table based on map file and efi file')
    else:
        print('Fail to generate Patch PCD Table for fail to find map file or efi file!')
