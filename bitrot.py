#!/usr/bin/env python
# -*- coding: utf-8 -*-

# Copyright (C) 2013 by Łukasz Langa

# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:

# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.

# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
# THE SOFTWARE.

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function
from __future__ import unicode_literals
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor, as_completed
from multiprocessing import freeze_support
import argparse
import atexit
import datetime
from datetime import timedelta
import errno
import hashlib
import os
from os import path
from sys import platform as _platform
import pathlib
import shutil
import sqlite3
import stat
import sys
import tempfile
import time
import progressbar
import smtplib
from fnmatch import fnmatch
import email.utils
from email.mime.text import MIMEText
#import binascii
#from zlib import crc32
import zlib
import re
import unicodedata
import gc

################### USER CONFIG ###################
RECEIVER = 'RECEIVER@gmail.com'
SENDER = 'SENDER@gmail.com'
PASSWORD = 'PASSWORD'
SERVER = smtplib.SMTP('smtp.gmail.com', 587)
DEFAULT_HASH_FUNCTION = "SHA512"
DEFAULT_CHUNK_SIZE = 1048576 # used to be 16384 - block size in HFS+; 4X the block size in ext4
DEFAULT_COMMIT_INTERVAL = 300
###################################################

DOT_THRESHOLD = 2
VERSION = (1, 0, 1)
IGNORED_FILE_SYSTEM_ERRORS = {errno.ENOENT, errno.EACCES, errno.EINVAL}
FSENCODING = sys.getfilesystemencoding()
SOURCE_DIR='.'
SOURCE_DIR_PATH = '.'
DESTINATION_DIR=SOURCE_DIR
HASHPROGRESSCOUNTER = 0
LENPATHS = 0

if sys.version[0] == '2':
    str = type(u'text')
    # use \'bytes\' for bytestrings

def sendEmail(MESSAGE="", SUBJECT="", log=True, verbosity=1):
    SERVER.ehlo()
    SERVER.starttls()
    SERVER.login(SENDER, PASSWORD)

    BODY = '\r\n'.join(['To: %s' % RECEIVER,
                        'From: %s' % SENDER,
                        'Subject: %s' % SUBJECT,
                        '', MESSAGE])

    try:
        SERVER.sendmail(SENDER, [RECEIVER], BODY)
        printAndOrLog("Email '{}' sent from {} to {}".format(SUBJECT,SENDER,RECEIVER))
    except Exception as err:
        printAndOrLog('Email sending error: {}'.format(err))
    SERVER.quit()

def normalize_path(path):
    if FSENCODING == 'utf-8' or FSENCODING == 'UTF-8':
        return unicodedata.normalize('NFKD', str(path))
    else:
        return path

def printAndOrLog(stringToProcess, log=True, stream=sys.stdout):
    print(stringToProcess,file=stream)
    if (log):
        writeToLog(log, '\n')
        writeToLog(log, stringToProcess)

def writeToLog(log = True, stringToWrite=""):
    log_path = get_absolute_path(log, SOURCE_DIR_PATH,ext=b'log')
    stringToWrite = cleanString(stringToWrite)
    try:
        with open(log_path, 'a') as logFile:
            logFile.write(stringToWrite)
            logFile.close()
    except Exception as err:
        print("Could not open log: \'{}\'. Received error: {}".format(log_path, err))

def writeToSFV(stringToWrite="", sfv="",log=True):
    if (sfv == "MD5"):
        sfv_path = get_absolute_path(log, SOURCE_DIR_PATH,ext=b'md5')
    elif (sfv == "SFV"):
        sfv_path = get_absolute_path(log, SOURCE_DIR_PATH,ext=b'sfv')
    try:
        with open(sfv_path, 'a') as sfvFile:
            sfvFile.write(stringToWrite)
            sfvFile.close()
    except Exception as err:
        printAndOrLog("Could not open checksum file: \'{}\'. Received error: {}".format(sfv_path, err),log)

def print_statusline(msg: str, offset = 0):
    last_msg_length = len(print_statusline.last_msg) if hasattr(print_statusline, 'last_msg') else 0
    print(' ' * (last_msg_length  + offset), end='\r')
    print(msg, end='\r')
    sys.stdout.flush()  # Some say they needed this, I didn't.
    print_statusline.last_msg = msg

def str2bool(v):
    if isinstance(v, bool):
       return v
    if v.lower() in ('yes', 'true', 't', 'y', '1'):
        return True
    elif v.lower() in ('no', 'false', 'f', 'n', '0'):
        return False
    else:
        raise argparse.ArgumentTypeError('Boolean value expected.')
def has_hidden_attribute(filepath):
    return bool(os.stat(filepath).st_file_attributes & stat.FILE_ATTRIBUTE_HIDDEN)

def integrityHash(path, chunk_size=DEFAULT_CHUNK_SIZE, algorithm=DEFAULT_HASH_FUNCTION):
    if (algorithm == "MD5"):
        if(os.stat(path).st_size) == 0:
            return "d41d8cd98f00b204e9800998ecf8427e"
        else:
            digest=hashlib.md5()          
    elif (algorithm == "SHA1"):
        if(os.stat(path).st_size) == 0:
            return "da39a3ee5e6b4b0d3255bfef95601890afd80709"
        else:
            digest=hashlib.sha1()
    elif (algorithm == "SHA224"):
        if(os.stat(path).st_size) == 0:
            return "d14a028c2a3a2bc9476102bb288234c415a2b01f828ea62ac5b3e42f"
        else:
            digest=hashlib.sha224()
    elif (algorithm == "SHA384"):
        if(os.stat(path).st_size) == 0:
            return "38b060a751ac96384cd9327eb1b1e36a21fdb71114be07434c0cc7bf63f6e1da274edebfe76f65fbd51ad2f14898b95b"
        else:
            digest=hashlib.sha384()
    elif (algorithm == "SHA256"):
        if(os.stat(path).st_size) == 0:
            return "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        else:
            digest=hashlib.sha256()
    elif (algorithm == "SHA512"):
        if(os.stat(path).st_size) == 0:
            return "cf83e1357eefb8bdf1542850d66d8007d620e4050b5715dc83f4a921d36ce9ce47d0d13c5d85f2b0ff8318d2877eec2f63b931bd47417a81a538327af927da3e"
        else:
            digest=hashlib.sha512() 
    else:
        #You should never get here
        printAndOrLog('Invalid hash function detected.',log)
        raise BitrotException('Invalid hash function detected.')
    try:
        if os.path.exists(path):
            with open(path, 'rb') as f:
                d = f.read(chunk_size)
                while d:
                    digest.update(d)
                    d = f.read(chunk_size)
                f.close()
    except Exception as err:
        printAndOrLog("Could not open file: \'{}\'. Received error: {}".format(path, err),log)
    return digest.hexdigest()

def hash(path, bar, format_custom_text, chunk_size=DEFAULT_CHUNK_SIZE, algorithm=DEFAULT_HASH_FUNCTION, verbosity=True, log=True, sfv=""):
    #0 byte files:
    # md5 d41d8cd98f00b204e9800998ecf8427e
    # LM  aad3b435b51404eeaad3b435b51404ee
    # NTLM    31d6cfe0d16ae931b73c59d7e0c089c0
    # sha1    da39a3ee5e6b4b0d3255bfef95601890afd80709
    # sha256  e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
    # sha384  38b060a751ac96384cd9327eb1b1e36a21fdb71114be07434c0cc7bf63f6e1da274edebfe76f65fbd51ad2f14898b95b
    # sha512  cf83e1357eefb8bdf1542850d66d8007d620e4050b5715dc83f4a921d36ce9ce47d0d13c5d85f2b0ff8318d2877eec2f63b931bd47417a81a538327af927da3e
    # md5(md5())  74be16979710d4c4e7c6647856088456
    # MySQL4.1+   be1bdec0aa74b4dcb079943e70528096cca985f8
    # ripemd160   9c1185a5c5e9fc54612808977ee8f548b2258d31
    # whirlpool   19fa61d75522a4669b44e39c1d2e1726c530232130d407f89afee0964997f7a73e83be698b288febcf88e3e03c4f0757ea8964e59b63d93708b138cc42a66eb3
    # adler32 00000001
    # crc32   00000000
    # crc32b  00000000
    # fnv1a32 811c9dc5
    # fnv1a64 cbf29ce484222325
    # fnv132  811c9dc5
    # fnv164  cbf29ce484222325
    # gost    ce85b99cc46752fffee35cab9a7b0278abb4c2d2055cff685af4912c49490f8d
    # gost-crypto 981e5f3ca30c841487830f84fb433e13ac1101569b9c13584ac483234cd656c0
    # haval128,3  c68f39913f901f3ddf44c707357a7d70
    # haval128,4  ee6bbf4d6a46a679b3a856c88538bb98
    # haval128,5  184b8482a0c050dca54b59c7f05bf5dd
    # haval160,3  d353c3ae22a25401d257643836d7231a9a95f953
    # haval160,4  1d33aae1be4146dbaaca0b6e70d7a11f10801525
    # haval160,5  255158cfc1eed1a7be7c55ddd64d9790415b933b
    # haval192,3  e9c48d7903eaf2a91c5b350151efcb175c0fc82de2289a4e
    # haval192,4  4a8372945afa55c7dead800311272523ca19d42ea47b72da
    # haval192,5  4839d0626f95935e17ee2fc4509387bbe2cc46cb382ffe85
    # haval224,3  c5aae9d47bffcaaf84a8c6e7ccacd60a0dd1932be7b1a192b9214b6d
    # haval224,4  3e56243275b3b81561750550e36fcd676ad2f5dd9e15f2e89e6ed78e
    # haval224,5  4a0513c032754f5582a758d35917ac9adf3854219b39e3ac77d1837e
    # haval256,3  4f6938531f0bc8991f62da7bbd6f7de3fad44562b8c6f4ebf146d5b4e46f7c17
    # haval256,4  c92b2e23091e80e375dadce26982482d197b1a2521be82da819f8ca2c579b99b
    # haval256,5  be417bb4dd5cfb76c7126f4f8eeb1553a449039307b1a3cd451dbfdc0fbbe330
    # joaat   00000000
    # md2 8350e5a3e24c153df2275c9f80692773
    # md4 31d6cfe0d16ae931b73c59d7e0c089c0
    # ripemd128   cdf26213a150dc3ecb610f18f6b38b46
    # ripemd256   02ba4c4e5f8ecd1877fc52d64d30e37a2d9774fb1e5d026380ae0168e3c5522d
    # ripemd320   22d65d5661536cdc75c1fdf5c6de7b41b9f27325ebc61e8557177d705a0ec880151c3a32a00899b8
    # sha224  d14a028c2a3a2bc9476102bb288234c415a2b01f828ea62ac5b3e42f
    # snefru  8617f366566a011837f4fb4ba5bedea2b892f3ed8b894023d16ae344b2be5881
    # snefru256   8617f366566a011837f4fb4ba5bedea2b892f3ed8b894023d16ae344b2be5881
    # tiger128,3  3293ac630c13f0245f92bbb1766e1616
    # tiger128,4  24cc78a7f6ff3546e7984e59695ca13d
    # tiger160,3  3293ac630c13f0245f92bbb1766e16167a4e5849
    # tiger160,4  24cc78a7f6ff3546e7984e59695ca13d804e0b68
    # tiger192,3  3293ac630c13f0245f92bbb1766e16167a4e58492dde73f3
    # tiger192,4  24cc78a7f6ff3546e7984e59695ca13d804e0b686e255194
    global HASHPROGRESSCOUNTER
    if (algorithm == "MD5"):
        if(os.stat(path).st_size) == 0:
            return "d41d8cd98f00b204e9800998ecf8427e"
        else:
            digest=hashlib.md5()          
    elif (algorithm == "SHA1"):
        if(os.stat(path).st_size) == 0:
            return "da39a3ee5e6b4b0d3255bfef95601890afd80709"
        else:
            digest=hashlib.sha1()
    elif (algorithm == "SHA224"):
        if(os.stat(path).st_size) == 0:
            return "d14a028c2a3a2bc9476102bb288234c415a2b01f828ea62ac5b3e42f"
        else:
            digest=hashlib.sha224()
    elif (algorithm == "SHA384"):
        if(os.stat(path).st_size) == 0:
            return "38b060a751ac96384cd9327eb1b1e36a21fdb71114be07434c0cc7bf63f6e1da274edebfe76f65fbd51ad2f14898b95b"
        else:
            digest=hashlib.sha384()
    elif (algorithm == "SHA256"):
        if(os.stat(path).st_size) == 0:
            return "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        else:
            digest=hashlib.sha256()
    elif (algorithm == "SHA512"):
        if(os.stat(path).st_size) == 0:
            return "cf83e1357eefb8bdf1542850d66d8007d620e4050b5715dc83f4a921d36ce9ce47d0d13c5d85f2b0ff8318d2877eec2f63b931bd47417a81a538327af927da3e"
        else:
            digest=hashlib.sha512() 
    else:
        #You should never get here
        printAndOrLog('Invalid hash function detected.',log)
        raise BitrotException('Invalid hash function detected.')
    try:
        if os.path.exists(path):
            with open(path, 'rb') as f:
                d = f.read(chunk_size)
                while d:
                    if (verbosity):
                        format_custom_text.update_mapping(f=progressFormat(path))
                        bar.update(HASHPROGRESSCOUNTER)
                    digest.update(d)
                    d = f.read(chunk_size)
                f.close()
    except Exception as err:
        printAndOrLog("Could not open file: \'{}\'. Received error: {}".format(path, err),log)
    if (sfv != ""):
        if (sfv == "MD5" and algorithm.upper() == "MD5"):
            sfvDigest = digest.hexdigest()
            writeToSFV(stringToWrite="{} {}\n".format(sfvDigest,"*"+normalize_path(path)),sfv=sfv,log=log) 
        elif (sfv == "MD5"):
            sfvDigest = hashlib.md5()
            try:
                if os.path.exists(path):
                    with open(path, 'rb') as f2:
                        d2 = f2.read(chunk_size)
                        while d2:
                            sfvDigest.update(d2)
                            d2 = f2.read(chunk_size)
                        f2.close
            except Exception as err:
                printAndOrLog("Could not open file: \'{}\'. Received error: {}".format(path, err),log)
            writeToSFV(stringToWrite="{} {}\n".format(sfvDigest.hexdigest(),"*"+normalize_path(path)),sfv=sfv,log=log) 
        elif (sfv == "SFV"):
            try:
                if os.path.exists(path):
                    with open(path, 'rb') as f2:
                        d2 = f2.read(chunk_size)
                        crcvalue = 0
                        while d2:
                            #zlib is faster
                            #import timeit
                            #print("b:", timeit.timeit("binascii.crc32(data)", setup="import binascii, zlib; data=b'X'*4096", number=100000))
                            #print("z:", timeit.timeit("zlib.crc32(data)",     setup="import binascii, zlib; data=b'X'*4096", number=100000))
                            #Result:
                            #b: 1.0176826480001182
                            #z: 0.4006126120002591
                            
                            crcvalue = (zlib.crc32(d2, crcvalue) & 0xFFFFFFFF)
                            #crcvalue = (binascii.crc32(d2,crcvalue) & 0xFFFFFFFF)
                            d2 = f2.read(chunk_size)
                        f2.close()
            except Exception as err:
                printAndOrLog("Could not open SFV file: \'{}\'. Received error: {}".format(path, err),log)
            writeToSFV(stringToWrite="{} {}\n".format(path, "%08X" % crcvalue),sfv=sfv,log=log)
    return digest.hexdigest()

def is_int(val):
    if type(val) == int:
        return True
    else:
        if val.is_integer():
            return True
        else:
            return False

def isValidHashingFunction(stringToValidate=""):
    hashFunctions = ["SHA1", "SHA224", "SHA384", "SHA256", "SHA512", "MD5"]
    if stringToValidate in hashFunctions:
        return True
    else:
        return False
    
#    if  (stringToValidate.upper() == "SHA1"
#      or stringToValidate.upper() == "SHA224"
#      or stringToValidate.upper() == "SHA384"
#      or stringToValidate.upper() == "SHA256"
#      or stringToValidate.upper() == "SHA512"
#      or stringToValidate.upper() == "MD5"):
#        return True
#    else:
#        return False

def calculateUnits(total_size = 0):
        units = ["B", "KB", "MB", "GB", "TB", "PB", "EB", "ZB", "YB"]
        size = 0
    
        #  Divides total size until it is less than 1024
        while total_size >= 1024:
            total_size = total_size/1024
            size = size + 1  # Size is used as the index for Units
        
        sizeUnits = units[size]
            
#        if (total_size/1024/1024/1024/1024/1024/1024/1024/1024 >= 1):
#            sizeUnits = "YB"
#            total_size = total_size/1024/1024/1024/1024/1024/1024/1024/1024
#        elif (total_size/1024/1024/1024/1024/1024/1024/1024 >= 1):
#            sizeUnits = "ZB"
#            total_size = total_size/1024/1024/1024/1024/1024/1024/1024
#        elif (total_size/1024/1024/1024/1024/1024/1024 >= 1):
#            sizeUnits = "EB"
#            total_size = total_size/1024/1024/1024/1024/1024/1024
#        elif (total_size/1024/1024/1024/1024/1024 >= 1):
#            sizeUnits = "PB"
#            total_size = total_size/1024/1024/1024/1024/1024
#        elif (total_size/1024/1024/1024/1024 >= 1):
#            sizeUnits = "TB"
#            total_size = total_size/1024/1024/1024/1024
#        elif (total_size/1024/1024/1024 >= 1):
#            sizeUnits = "GB"
#            total_size = total_size/1024/1024/1024
#        elif (total_size/1024/1024 >= 1):
#            sizeUnits = "MB"
#            total_size = total_size/1024/1024
#        elif (total_size/1024 >= 1):
#            sizeUnits = "KB"
#            total_size = total_size/1024
#        else:
#            sizeUnits = "B"
#            total_size = total_size
        return sizeUnits, total_size

def cleanString(stringToClean=""):
    #stringToClean=re.sub(r'[\\/*?:"<>|]',"",stringToClean)
    stringToClean = ''.join([x for x in stringToClean if ord(x) < 128])
    return stringToClean

def isDirtyString(stringToCheck=""):
    comparisonString = stringToCheck
    cleanedString = cleanString(stringToCheck)
    if (cleanedString == comparisonString):
        return False
    else:
        return True

def progressFormat(current_path): 
    terminal_size = shutil.get_terminal_size()
    cols = terminal_size.columns
    max_path_size =  int(shutil.get_terminal_size().columns/2)
    if len(current_path) > max_path_size:
        # show first half and last half, separated by ellipsis
        # e.g. averylongpathnameaveryl...ameaverylongpathname
        half_mps = (max_path_size - 3) // 2
        current_path = current_path[:half_mps] + '...' + current_path[-half_mps:]
    else:
        # pad out with spaces, otherwise previous filenames won't be erased
        current_path += ' ' * (max_path_size - len(current_path))
    current_path = current_path + '|'
    return current_path

def ts():
    return datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S%z')

def get_sqlite3_cursor(path, copy=False, log=True):
    if (copy):
        if not os.path.exists(path):
            raise ValueError("Error: bitrot database at {} does not exist.".format(path))
            printAndOrLog("Error: bitrot database at {} does not exist.".format(path),log)
        db_copy = tempfile.NamedTemporaryFile(prefix='bitrot_', suffix='.db',
                                              delete=False)
        try:
            if os.path.exists(path):
                with open(path, 'rb') as db_orig:
                    try:
                        shutil.copyfileobj(db_orig, db_copy)
                    finally:
                        db_copy.close()
                        db_orig.close()
        # except IOError as e:
        #     if e.errno == errno.EACCES:
        except Exception as e:
            printAndOrLog("Could not open database file: \'{}\'. Received error: {}".format(path, e),log)
            raise BitrotException("Could not open database file: \'{}\'. Received error: {}".format(path, e))

        path = db_copy.name
        atexit.register(os.unlink, path)
    try:
        conn = sqlite3.connect(path)
    except Exception as err:
           printAndOrLog("Could not connect to database: \'{}\'. Received error: {}".format(path, err),log)
           raise BitrotException("Could not connect to database: \'{}\'. Received error: {}".format(path, err))
    atexit.register(conn.close)
    cur = conn.cursor()
    tables = set(t for t, in cur.execute('SELECT name FROM sqlite_master'))

    if 'bitrot' not in tables:
        cur.execute('CREATE TABLE bitrot (path TEXT PRIMARY KEY, '
                    'mtime INTEGER, hash TEXT, timestamp TEXT)')
    if 'bitrot_hash_idx' not in tables:
        cur.execute('CREATE INDEX bitrot_hash_idx ON bitrot (hash)')
    atexit.register(conn.commit)
    return conn

def fix_existing_paths(directory=SOURCE_DIR, verbosity = 1, log=True, test = 0, fix=5, warnings = (), fixedRenameList = (), fixedRenameCounter = 0):
#   Use os.getcwd() instead of "." since it doesn't seem to be resolved the way you want. This will be illustrated in the diagnostics function.
#   Use relative path renaming by os.chdir(root). Of course using correct absolute paths also works, but IMHO relative paths are just more elegant.
#   Pass an unambiguous string into os.walk() as others have mentioned.
#   Also note that topdown=False in os.walk() doesn't matter. Since you are not renaming directories, the directory structure will be invariant during os.walk().
    progressCounter=0
    if verbosity:
        print("Scanning file and directory names to fix... Please wait...")
        bar = progressbar.ProgressBar(max_value=progressbar.UnknownLength)
        start = time.time()
    for root, dirs, files in os.walk(directory, topdown=False):
        for file in files:
            if (isDirtyString(file)):
                if (fix == 2) or (fix == 3):
                    warnings.append(file)
                    printAndOrLog('Warning: Invalid character detected in filename\'{}\''.format(os.path.join(root, file)), log, sys.stderr)
                if (not test):
                    try:
                        # chdir before renaming
                        #os.chdir(root)
                        #fullfilename=os.path.abspath(file)
                        #os.rename(f, cleanString(file))  # relative path, more elegant
                        pathBackup = file
                        if (fix == 2) or (fix == 3):
                            os.rename(os.path.join(root, f), os.path.join(root, cleanString(file)))
                        path = cleanString(file)
                    except Exception as ex:
                        warnings.append(file)
                        printAndOrLog('Can\'t rename: {} due to warning: \'{}\''.format(os.path.join(root, f),ex), log ,sys.stderr)
                        continue
                else:
                    fixedRenameList.append([])
                    fixedRenameList.append([])
                    fixedRenameList[fixedRenameCounter].append(os.path.join(root, pathBackup))
                    fixedRenameList[fixedRenameCounter].append(os.path.join(root, path))
                    fixedRenameCounter += 1
                    if verbosity:
                        progressCounter+=1
                        # statusString = "Files:" + str(progressCounter) + " Elapsed:" + recordTimeElapsed(start) + " " + progressFormat(path)
                        # print_statusline(statusString,15)
                        bar.update(progressCounter)
        for directory in dirs:
            if (isDirtyString(directory)):
                if (not test):
                    try:
                        # chdir before renaming
                        #os.chdir(root)
                        #fullfilename=os.path.abspath(d)
                        pathBackup = directory
                        if (fix == 2) or (fix == 3):
                            os.rename(os.path.join(root, directory), os.path.join(root, cleanString(d)))
                        #os.rename(d, cleanString(d))  # relative path, more elegant
                        cleanedDirctory = cleanString(directory)
                    except Exception as ex:
                        warnings.append(d)
                        printAndOrLog('Can\'t rename: {} due to warning: \'{}\''.format(os.path.join(root, directory),ex), log, sys.stderr)
                        continue
                    else:
                        fixedRenameList.append([])
                        fixedRenameList.append([])
                        fixedRenameList[fixedRenameCounter].append(os.path.join(root, pathBackup))
                        fixedRenameList[fixedRenameCounter].append(os.path.join(root, cleanedDirctory))
                        fixedRenameCounter += 1
                        if verbosity:
                            progressCounter+=1
                            bar.update(progressCounter)
    if verbosity:
        print()
        bar.finish()
    return fixedRenameList, fixedRenameCounter

def list_existing_paths(directory=SOURCE_DIR, expected=(), excluded=(), included=(), 
                        verbosity=1, follow_links=False, log=True, hidden=True, fix=0, warnings = ()): #normalize=False,
    """list_existing_paths(b'/dir') -> ([path1, path2, ...], total_size)

    Returns a tuple with a set of existing files in 'directory' and its subdirectories
    and their 'total_size'. If directory was a bytes object, so will be the returned
    paths.

     Doesn't add entries listed in 'excluded'.  Doesn't add symlinks if
    'follow_links' is False (the default).  All entries present in 'expected'
    must be files (can't be directories or symlinks).
    """
    # excluded = [get_relative_path(pathIterator) for pathIterator in excluded]
    # excluded = [pathIterator.decode(FSENCODING) for pathIterator in excluded]


    paths = set()
    total_size = 0
    excludedList = []
    progressCounter=0

    if verbosity:
        print("Mapping all files... Please wait...")
        start = time.time()
        format_custom_text = progressbar.FormatCustomText(
                '%(f)s',
                dict(
                    f='',
                )
            )
        bar = progressbar.ProgressBar(max_value=progressbar.UnknownLength)
    for pathIterator, _, files in os.walk("."):
        for f in files:
            path = os.path.join(pathIterator, f)
            path = normalize_path(path)
                
            try:
                if os.path.islink(path):
                    if follow_links:
                        st = os.stat(path)
                    else:
                        st = os.lstat(path)
                else:
                    st = os.lstat(path)
            except OSError as ex:
                if ex.errno not in IGNORED_FILE_SYSTEM_ERRORS:
                    raise BitrotException("Unhandled file system error: []}".format(ex.errno))
            else:
                # split path /dir1/dir2/file.txt into
                # ['dir1', 'dir2', 'file.txt']
                # and match on any of these components
                # so we could use 'dir*', '*2', '*.txt', etc. to exclude anything

                try:
                    exclude_this = [fnmatch(file, wildcard)
                                    for file in pathIterator.split(os.path.sep)
                                    for wildcard in excluded]
                except UnicodeEncodeError:
                    printAndOrLog("Warning: cannot encode file name: {}".format(path), log, sys.stderr)
                    continue
                try:
                    include_this = [fnmatch(file, wildcard)
                                    for file in pathIterator.split(os.path.sep)
                                    for wildcard in included]
                except UnicodeEncodeError:
                    printAndOrLog("Warning: cannot encode file name: {}".format(path), log, sys.stderr)
                    continue

                if (not stat.S_ISREG(st.st_mode) and not os.path.islink(path)) or any(exclude_this) or any([fnmatch(path, exc) for exc in excluded]) or (included and not any([fnmatch(path, inc) for inc in included]) and not any(include_this)):
                #if not stat.S_ISREG(st.st_mode) or any([fnmatch(path, exc) for exc in excluded]):
                    excludedList.append(path)
                elif (not hidden and has_hidden_attribute(path)):
                        excludedList.append(path)
                else:
                    # if (normalize):
                    #     oldMatch = ""
                    #     for filePath in paths:
                    #         if normalize_path(path) == normalize_path(filePath):
                    #             oldMatch = filePath
                    #             break
                    #     if oldMatch != "":
                    #         oldFile = os.stat(oldMatch)
                    #         new_mtime = int(st.st_mtime)
                    #         old_mtime = int(oldFile.st_mtime)
                    #         new_atime = int(st.st_atime)
                    #         old_atime = int(oldFile.st_atime)
                    #         now_date = datetime.datetime.now()
                    #         if not new_mtime or not new_atime:
                    #             nowTime = time.mktime(now_date.timetuple())
                    #         if not old_mtime or not old_atime:
                    #             nowTime = time.mktime(now_date.timetuple())
                    #         if not new_mtime and not new_atime:
                    #             new_mtime = int(nowTime)
                    #             new_atime = int(nowTime)
                    #         elif not (new_mtime):
                    #             new_mtime = int(nowTime)
                    #         elif not (new_atime):
                    #             new_atime = int(nowTime)
                    #         if not old_mtime and not old_atime:
                    #             old_mtime = int(nowTime)
                    #             old_atime = int(nowTime)
                    #         elif not (old_mtime):
                    #             old_mtime = int(nowTime)
                    #         elif not (old_atime):
                    #             old_atime = int(nowTime)

                    #         new_mtime_date = datetime.datetime.fromtimestamp(new_mtime)
                    #         new_atime_date = datetime.datetime.fromtimestamp(new_atime)
                    #         old_mtime_date = datetime.datetime.fromtimestamp(old_mtime)
                    #         old_atime_date = datetime.datetime.fromtimestamp(old_atime)

                    #         delta_new_mtime_date = now_date - new_mtime_date
                    #         delta_new_atime_date = now_date - new_atime_date

                    #         delta_old_mtime_date = now_date - old_mtime_date
                    #         delta_old_atime_date = now_date - old_atime_date

                    #         if delta_new_mtime_date < delta_old_mtime_date:
                    #             paths.add(path)
                    #             paths.discard(filePath)
                    #             total_size += st.st_size
                    #         elif delta_new_atime_date < delta_old_atime_date:
                    #             paths.add(path)
                    #             paths.discard(filePath)
                    #             total_size += st.st_size
                    #         else:
                    #             pass
                    #     else:
                    #         paths.add(path)
                    #         total_size += st.st_size
                    # else:
                    paths.add(path)
                    total_size += st.st_size
                if verbosity:
                    progressCounter+=1
                    # statusString = "Files:" + str(progressCounter) + " Elapsed:" + recordTimeElapsed(start) + " " + progressFormat(path)
                    # print_statusline(statusString,15)
                    bar.update(progressCounter) 

    if verbosity:
        bar.finish()
        print()
    return paths, total_size, excludedList
def compute_one(path, bar, format_custom_text, chunk_size, algorithm="", follow_links=False, verbosity = 1, log=True, sfv=""):
    """Return a tuple with (unicode path, size, mtime, sha1). Takes a binary path."""
    global HASHPROGRESSCOUNTER
    if (verbosity):
        HASHPROGRESSCOUNTER+=1

    try:
        if os.path.islink(path):
            if follow_links:
                st = os.stat(path)
            else:
                st = os.lstat(path)
        else:
            st = os.lstat(path)

    except OSError as ex:
        if ex.errno in IGNORED_FILE_SYSTEM_ERRORS:
            # The file disappeared between listing existing paths and
            # this run or is (temporarily?) locked with different
            # permissions. We'll just skip it for now.
            printAndOrLog('warning: `{}` is currently unavailable for reading: {}'.format(path, ex), log, sys.stderr)
            raise BitrotException

        raise   # Not expected? https://github.com/ambv/bitrot/issues/

    try:
        new_hash = hash(path, bar, format_custom_text, chunk_size, algorithm, verbosity, log, sfv)
    except (IOError, OSError) as e:
        printAndOrLog('warning: cannot compute hash of {} [{}]'.format(path, errno.errorcode[e.args[0]],), log, sys.stderr)
        raise BitrotException
    return path, st.st_size, int(st.st_mtime), int(st.st_atime), new_hash

class CustomETA(progressbar.widgets.ETA):

    def __call__(self, progress, data):
        # Run 'ETA.__call__' to update 'data'. This adds the 'eta_seconds'
        data_plus_one = data.copy()
        if (HASHPROGRESSCOUNTER == 1):
            data_plus_one['value'] += 1
            data_plus_one['percentage'] = ((HASHPROGRESSCOUNTER )/ LENPATHS * 100.0)
        formatted = progressbar.widgets.ETA.__call__(self, progress, data_plus_one)

        # ETA might not be available, if the maximum length is not available
        # for example
        if data.get('eta'):
            # By using divmod we can split the timedelta to hours and the
            # remaining timedelta
            hours, delta = divmod(
                timedelta(seconds=int(data['eta_seconds'])),
                timedelta(hours=1),
            )
            data['eta'] = ' {hours}{delta_truncated}'.format(
                hours=hours,
                # Strip the 0 hours from the timedelta
                delta_truncated=str(delta).lstrip('0'),
            )
            return progressbar.widgets.Timer.__call__(self, progress, data, format=self.format)
        else:
            return formatted

class BitrotException(Exception):
    pass

class Bitrot(object):
    def __init__(
        self, verbosity=1, email = False, log = False, hidden = True, test=0, recent = 0, follow_links=False, commit_interval=300,
        chunk_size=DEFAULT_CHUNK_SIZE, workers=os.cpu_count(), include_list=[], exclude_list=[], algorithm="", sfv="MD5", fix=0, normalize=False
    ):
        self.verbosity = verbosity
        self.test = test
        self.recent = recent
        self.follow_links = follow_links
        self.commit_interval = commit_interval
        self.chunk_size = chunk_size
        self.include_list = include_list
        self.exclude_list = exclude_list
        self._last_reported_size = ''
        self._last_commit_ts = 0
        #ProcessPoolExecutor runs each of your workers in its own separate child process. (CPU Bound)
        #ThreadPoolExecutor runs each of your workers in separate threads within the main process. (IO Bound)
        self.workers = workers
        if (workers != 1):
            self.pool = ThreadPoolExecutor(max_workers=workers)
        self.email = email
        self.log = log
        self.hidden = hidden
        self.startTime = time.time()
        self.algorithm = algorithm
        self.sfv = sfv
        self.fix = fix
        self.normalize=normalize

    def maybe_commit(self, conn):
        if time.time() < self._last_commit_ts + self.commit_interval:
            # no time for commit yet!
            return

        conn.commit()
        self._last_commit_ts = time.time()

    def run(self):
        check_sha512_integrity(chunk_size=self.chunk_size, verbosity=self.verbosity, log=self.log)

        bitrot_sha512 = get_relative_path(get_absolute_path(self.log, SOURCE_DIR_PATH,ext=b'sha512'),self.log)
        bitrot_log = get_relative_path(get_absolute_path(self.log, SOURCE_DIR_PATH,ext=b'log'), self.log)
        bitrot_db = get_relative_path(get_absolute_path(self.log, SOURCE_DIR_PATH,b'db'), self.log)
        bitrot_sfv = get_relative_path(get_absolute_path(self.log, SOURCE_DIR_PATH,ext=b'sfv'), self.log)
        bitrot_md5 = get_relative_path(get_absolute_path(self.log, SOURCE_DIR_PATH,ext=b'md5'), self.log)

        #bitrot_db = os.path.basename(get_absolute_path())
        #bitrot_sha512 = os.path.basename(get_absolute_path(ext=b'sha512'))
        #bitrot_log = os.path.basename(get_absolute_path(ext=b'log'))

        if (not os.path.exists(bitrot_db) and self.test != 0):
            printAndOrLog("No database exists so cannot test. Run the tool once first.", self.log, sys.stderr)
            exit()

        try:
            conn = get_sqlite3_cursor(bitrot_db, copy=self.test, log=self.log)
        except ValueError:
            printAndOrLog("No database exists so cannot test. Run the tool once first.", self.log, sys.stderr)
            raise BitrotException('No database exists so cannot test. Run the tool once first.')

        cur = conn.cursor()
        futures = []
        new_paths = []
        missing_paths = []
        existing_paths = []
        updated_paths = []
        renamed_paths = []
        errors = []
        emails = []
        tooOldList = []
        temporary_paths = []
        warnings = []
        fixedRenameList = []
        fixedRenameCounter = 0
        fixedPropertiesList = []
        fixedPropertiesCounter = 0
        current_size = 0
        global HASHPROGRESSCOUNTER
        global LENPATHS

        missing_paths = self.select_all_paths(cur)
        hashes = self.select_all_hashes(cur)

        if (SOURCE_DIR != DESTINATION_DIR):
            os.chdir(DESTINATION_DIR)

        if (self.fix >= 1):
            fixedRenameList, fixedRenameCounter = fix_existing_paths(
            #os.getcwd(),# pass an unambiguous string instead of: b'.'  
            SOURCE_DIR,
            verbosity=self.verbosity,
            log=self.log,
            test=self.test,
            fix=self.fix,
            warnings=warnings,
            fixedRenameList = fixedRenameList,
            fixedRenameCounter = fixedRenameCounter
        )

        paths, total_size, excludedList = list_existing_paths(
            SOURCE_DIR,
            expected=missing_paths, 
            excluded=[bitrot_db, bitrot_sha512, bitrot_log, bitrot_sfv, bitrot_md5 ] + self.exclude_list,
            included=self.include_list,
            follow_links=self.follow_links,
            verbosity=self.verbosity,
            log=self.log,
            hidden=self.hidden,
            fix=self.fix,
            # normalize=self.normalize,
            warnings=warnings,

        )

        FIMErrorCounter = 0;

        paths = sorted(paths)
        LENPATHS = len(paths)

        #These are missing entries that have recently been excluded
        for pathIterator in missing_paths:
            if (pathIterator in excludedList):
                temporary_paths.append(pathIterator)
        for pathIterator in temporary_paths:
            missing_paths.discard(pathIterator)
            if (self.test == 0):
                cur.execute('DELETE FROM bitrot WHERE path=?', (pathIterator,))
        if temporary_paths:
             del temporary_paths

        if self.verbosity:
            print("Hashing all files... Please wait...")
            format_custom_text = progressbar.FormatCustomText('%(f)s',dict(f='',))
            bar = progressbar.ProgressBar(max_value=LENPATHS,widgets=[format_custom_text,
                CustomETA(format_not_started='%(value)01d/%(max_value)d|%(percentage)3d%%|Elapsed:%(elapsed)8s|ETA:%(eta)8s', format_finished='%(value)01d/%(max_value)d|%(percentage)3d%%|Elapsed:%(elapsed)8s', format='%(value)01d/%(max_value)d|%(percentage)3d%%|Elapsed:%(elapsed)8s|ETA:%(eta)8s', format_zero='%(value)01d/%(max_value)d|%(percentage)3d%%|Elapsed:%(elapsed)8s', format_NA='%(value)01d/%(max_value)d|%(percentage)3d%%|Elapsed:%(elapsed)8s'),
                progressbar.Bar(marker='#', left='|', right='|', fill=' ', fill_left=True),               
                ])

        if (self.workers == 1):
            pointer = paths
            if paths:
                 del paths
        else:
            futures = [self.pool.submit(compute_one, pathIterator, bar, format_custom_text, self.chunk_size, self.algorithm, self.follow_links, self.verbosity, self.log, self.sfv) for pathIterator in paths]
            pointer = as_completed(futures)
            if futures:
                del futures
        gc.collect()

        for future in pointer:
            if (self.workers == 1):
                path = future
                try:
                    st = os.stat(path)
                except OSError as ex:
                    if ex.errno in IGNORED_FILE_SYSTEM_ERRORS:
                        # The file disappeared between listing existing paths and
                        # this run or is (temporarily?) locked with different
                        # permissions. We'll just skip it for now.
                        printAndOrLog('warning: `{}` is currently unavailable for reading: {}'.format(path, ex), self.log, sys.stderr)
                        continue
                    raise
            else:
                try:
                    path, new_size, new_mtime, new_atime, new_hash = future.result()
                except BitrotException:
                    continue

            if (self.workers == 1):
                if self.verbosity:
                    HASHPROGRESSCOUNTER+=1
                new_mtime = int(st.st_mtime)
                new_atime = int(st.st_atime)
                new_size = st.st_size
            new_mtime_orig = new_mtime
            new_atime_orig = new_atime
            a = datetime.datetime.now()
            
            #Used for testing bad file timestamps
            #os.utime(path, (0,0))
            #continue
            
            if not new_mtime or not new_atime:
                nowTime = time.mktime(a.timetuple())
            if not new_mtime and not new_atime:
                new_mtime = int(nowTime)
                new_atime = int(nowTime)
                if (self.fix  == 1) or (self.fix  == 3):
                    warnings.append(path)
                    printAndOrLog('Warning: \'{}\' has an invalid access and modification date. Try running with -f to fix.'.format(path),self.log)
            elif not (new_mtime):
                new_mtime = int(nowTime)
                if (self.fix  == 1) or (self.fix  == 3):
                    warnings.append(path)
                    printAndOrLog('Warning: \'{}\' has an invalid modification date. Try running with -f to fix.'.format(path),self.log)
            elif not (new_atime):
                new_atime = int(nowTime)
                if (self.fix  == 1) or (self.fix  == 3):
                    warnings.append(path)
                    printAndOrLog('Warning: \'{}\' has an invalid access date. Try running with -f to fix.'.format(path),self.log)

            b = datetime.datetime.fromtimestamp(new_mtime)
            c = datetime.datetime.fromtimestamp(new_atime)

            if (self.recent >= 1):
                delta = a - b
                delta2= a - c
                if (delta.days > self.recent or delta2.days > self.recent):
                    tooOldList.append(path)
                    missing_paths.discard(path)
                    total_size -= new_size
                    continue
            fixPropertyFailed = False
            if (not self.test):
                if not new_mtime_orig and not new_atime_orig:
                    if (self.fix  == 1) or (self.fix  == 3):
                        try:
                            os.utime(path, (nowTime,nowTime))
                        except Exception as ex:
                            warnings.append(f)
                            fixPropertyFailed = True
                            printAndOrLog('Can\'t rename: {} due to warning: \'{}\''.format(path,ex), self.log, sys.stderr)
                elif not (new_mtime_orig):
                    if (self.fix  == 1) or (self.fix  == 3):
                        try:
                            os.utime(path, (new_atime,nowTime))
                        except Exception as ex:
                            warnings.append(path)
                            fixPropertyFailed = True
                            printAndOrLog('Can\'t rename: {} due to warning: \'{}\''.format(path,ex), self.log, sys.stderr)
                elif not (new_atime_orig):
                    if (self.fix  == 1) or (self.fix  == 3):
                        try:
                            os.utime(path, (nowTime,new_mtime))
                        except Exception as ex:
                            warnings.append(f)
                            fixPropertyFailed = True
                            printAndOrLog('Can\'t rename: {} due to warning: \'{}\''.format(path,ex), self.log, sys.stderr)

            if not new_mtime_orig or not new_atime_orig:
                if (fixPropertyFailed == False):
                    if (self.fix  == 1) or (self.fix  == 3):
                            fixedPropertiesList.append([])
                            fixedPropertiesList.append([])
                            fixedPropertiesList[fixedPropertiesCounter].append(path)
                            fixedPropertiesCounter += 1

            current_size += new_size

            if (self.workers == 1):
                try:
                    new_hash = hash(path, bar, format_custom_text, self.chunk_size, self.algorithm, self.verbosity, self.log, self.sfv)
                except (IOError, OSError) as e:
                    printAndOrLog('warning: cannot compute hash of {} [{}]'.format(path, errno.errorcode[e.args[0]],), log, sys.stderr)
                    missing_paths.discard(path)
                    continue
            
            if path not in missing_paths:
                # We are not expecting this path, it wasn't in the database yet.
                # It's either new, a rename, or recently excluded. Let's handle that 
                if (self.workers == 1):
                    stored_path = self.handle_unknown_path(cur, path, new_mtime, new_hash, pointer, hashes, self.test, self.log)
                else:
                    stored_path = self.handle_unknown_path(cur, path, new_mtime, new_hash, paths, hashes, self.test, self.log)
                self.maybe_commit(conn)
                if path == stored_path:
                    new_paths.append(path)
                    missing_paths.discard(path)
                else:
                    renamed_paths.append((stored_path, path))
                    missing_paths.discard(stored_path)
                continue
            else:
                existing_paths.append(path)

            # At this point we know we're seeing an expected file.
            missing_paths.discard(path)
            cur.execute('SELECT mtime, hash, timestamp FROM bitrot WHERE path=?',(path,))
            row = cur.fetchone()
            if not row:
                printAndOrLog('warning: path disappeared from the database while running:', path, self.log, sys.stderr)
                continue

            stored_mtime, stored_hash, stored_ts = row
            if (self.test != 2):
                if (int(stored_mtime) != new_mtime):
                    updated_paths.append(path)
                    if (self.test == 0):
                        cur.execute('UPDATE bitrot SET mtime=?, hash=?, timestamp=? '
                                    'WHERE path=?',
                                    (new_mtime, new_hash, ts(), path))
                        self.maybe_commit(conn)
                    continue

            if stored_hash != new_hash:
                errors.append(path)
                emails.append([])
                emails.append([])
                emails[FIMErrorCounter].append(self.algorithm)
                emails[FIMErrorCounter].append(path)
                emails[FIMErrorCounter].append(stored_hash)
                emails[FIMErrorCounter].append(new_hash)
                emails[FIMErrorCounter].append(stored_ts)
                printAndOrLog(
                        '\n\nError: {} mismatch for {}\nExpected: {}\nGot:      {}'
                        '\nLast good hash checked on {}'.format(
                        #p, stored_hash, new_hash, stored_ts
                        self.algorithm,path, stored_hash, new_hash, stored_ts),self.log)   
                FIMErrorCounter += 1 

        if self.verbosity:    
            format_custom_text.update_mapping(f="")
            bar.finish()

        if (self.email):
            if (FIMErrorCounter >= 1):
                emailToSendString=""
                for i in range(0, FIMErrorCounter):
                    emailToSendString +="Error: {} mismatch for {} \nExpected: {}\nGot:      {}\n".format(emails[i][0],emails[i][1],emails[i][2],emails[i][3])
                    emailToSendString +="Last good hash checked on {}\n\n".format(emails[i][4])
                sendEmail(MESSAGE=emailToSendString, SUBJECT="FIM Error", log=self.log,verbosity=self.verbosity)
            
            if (self.test == 0):
                for pathIterator in missing_paths:
                    cur.execute('DELETE FROM bitrot WHERE path=?', (pathIterator,))

        conn.commit()

        if self.verbosity:
            cur.execute('SELECT COUNT(path) FROM bitrot')
            all_count = cur.fetchone()[0]
            self.report_done(
                total_size,
                all_count,
                len(errors),
                len(warnings),
                existing_paths,
                new_paths,
                updated_paths,
                renamed_paths,
                missing_paths,
                tooOldList,
                excludedList,
                fixedRenameList,
                fixedRenameCounter,
                fixedPropertiesList,
                fixedPropertiesCounter,
                self.log
            )

        # if total_size:
        #     del total_size
        # if all_count:
        #     del all_count
        # if errors:
        #     del errors
        # if warnings:
        #     del warnings
        # if existing_paths:
        #     del existing_paths
        # if new_paths:
        #     del new_paths
        # if updated_paths:
        #     del updated_paths
        # if renamed_paths:
        #     del renamed_paths
        # if missing_paths:
        #     del missing_paths
        # if tooOldList:
        #     del tooOldList
        # if excludedList:
        #     del excludedList
        # if fixedRenameList:
        #     del fixedRenameList
        # if fixedRenameCounter:
        #     del fixedRenameCounter
        # if fixedPropertiesList:
        #     del fixedPropertiesList
        # if fixedPropertiesCounter:
        #     del fixedPropertiesCounter
        # if pointer:
        #     del pointer
        # if emails:
        #     del emails
        # if current_size:
        #     del current_size
        # if bar:
        #     del bar
        # if format_custom_text:
        #     del format_custom_text
        # if paths:
        #     del paths
        # gc.collect()

        if (self.test == 0):
            cur.execute('vacuum')
            update_sha512_integrity(chunk_size=self.chunk_size, verbosity=self.verbosity, log=self.log)

        if self.test and self.verbosity:
            printAndOrLog('Database file not updated on disk (test mode).',self.log)

        if self.verbosity:
            printAndOrLog("Time elapsed: " + recordTimeElapsed(startTime = self.startTime))
            
        if warnings:
            if len(warnings) == 1:
                printAndOrLog('Warning: There was 1 warning found.',self.log)
            else:
                printAndOrLog('Warning: There were {} warnings found.'.format(len(warnings)),self.log)

        if errors:
            if len(errors) == 1:
                printAndOrLog('Error: There was 1 error found.',self.log)
            else:
                printAndOrLog('Error: There were {} errors found.'.format(len(errors)),self.log)

    def select_all_paths(self, cur):
        """Return a set of all distinct paths in the bitrot database.
        The paths are Unicode and are normalized if FSENCODING was UTF-8.
        """
        result = set()
        cur.execute('SELECT path FROM bitrot')
        row = cur.fetchone()
        while row:
            result.add(row[0])
            row = cur.fetchone()
        return result

    def select_all_hashes(self, cur):
        """Return a dict where keys are hashes and values are sets of paths.
        The paths are Unicode and are normalized if FSENCODING was UTF-8.
        """
        result = {}
        cur.execute('SELECT hash, path FROM bitrot')
        row = cur.fetchone()
        while row: 
            rhash, rpath = row
            result.setdefault(rhash, set()).add(rpath)
            row = cur.fetchone()
        return result

    def report_done(
        self, total_size, all_count, error_count, warning_count, existing_paths, new_paths, updated_paths,
        renamed_paths, missing_paths, tooOldList, excludedList, fixedRenameList, fixedRenameCounter,
        fixedPropertiesList, fixedPropertiesCounter, log):
        """Print a report on what happened.  All paths should be Unicode here."""

        sizeUnits , total_size = calculateUnits(total_size=total_size)
        totalFixed = fixedRenameCounter + fixedPropertiesCounter
        if self.verbosity >= 1:
            print()
            printAndOrLog('Finished. {:.2f} {} of data read.'.format(total_size,sizeUnits),log)
        
        if (error_count == 1):
            printAndOrLog('1 error found.',log)
        else:
            printAndOrLog('{} errors found.'.format(error_count),log)

        if (warning_count == 1):
            printAndOrLog('1 warning found.',log)
        else:
           printAndOrLog('{} warnings found.'.format(warning_count),log)

        if self.verbosity >= 1:
            if (all_count == 1):
                printAndOrLog(
                    '\n1 entry in the database, {} existing, {} new, {} updated, '
                    '{} renamed, {} missing, {} skipped, {} excluded, {} fixed'.format(
                        len(existing_paths), len(new_paths), len(updated_paths),
                        len(renamed_paths), len(missing_paths), len(tooOldList), len(excludedList), totalFixed),log)
            else:
                printAndOrLog(
                    '\n{} entries in the database, {} existing, {} new, {} updated, '
                    '{} renamed, {} missing, {} skipped, {} excluded, {} fixed.'.format(
                        all_count, len(existing_paths), len(new_paths), len(updated_paths),
                        len(renamed_paths), len(missing_paths), len(tooOldList), len(excludedList), totalFixed),log)

        if self.verbosity >= 5:
            if (existing_paths):
                if (len(existing_paths) == 1):
                    printAndOrLog('1 existing entry:',log)
                else:
                    printAndOrLog('{} existing entries:'.format(LENPATHS),log)
                existing_paths.sort()
                for pathIterator in existing_paths:
                    printAndOrLog('{}'.format(pathIterator),log)

        if self.verbosity >= 4:
            if (excludedList):
                if (len(excludedList) == 1):
                    printAndOrLog("1 files excluded: ",log)
                    for row in excludedList:
                        printAndOrLog("{}".format(row),log)
                else:
                    printAndOrLog("{} files excluded: ".format(len(excludedList)),log)
                    for row in excludedList:
                        printAndOrLog("{}".format(row),log)

                if (tooOldList):
                    if (len(tooOldList) == 1):
                        printAndOrLog("1 non-recent files excluded: ",log)
                        for row in tooOldList:
                            printAndOrLog("{}".format(row),log)
                    else:
                        printAndOrLog("{} non-recent files excluded".format(len(tooOldList)),log)
                        for row in tooOldList:
                            printAndOrLog("{}".format(row),log)

        if self.verbosity >= 3:
            if new_paths:
                if (len(new_paths) == 1):
                    printAndOrLog('1 new entry:',log)
                else:
                    printAndOrLog('{} new entries:'.format(len(new_paths)),log)

                new_paths.sort()
                for pathIterator in new_paths:
                    printAndOrLog('{}'.format(pathIterator),log)

            if updated_paths:
                if (len(updated_paths) == 1):
                   printAndOrLog('1 entry updated:',log)
                else:
                    printAndOrLog('{} entries updated:'.format(len(updated_paths)),log)

                updated_paths.sort()
                for pathIterator in updated_paths:
                    printAndOrLog(' {}'.format(pathIterator),log)

            if renamed_paths:
                if (len(renamed_paths) == 1):
                    printAndOrLog('1 entry renamed:',log)
                else:
                    printAndOrLog('{} entries renamed:'.format(len(renamed_paths)),log)

                renamed_paths.sort()
                for pathIterator in renamed_paths:
                    printAndOrLog(' from {} to {}'.format(pathIterator[0],pathIterator[1]),log)
                    
        if self.verbosity >= 2:
            if missing_paths:
                if (len(missing_paths) == 1):
                    printAndOrLog('1 entry missing:',log)
                else:
                    printAndOrLog('{} entries missing:'.format(len(missing_paths)),log)

                missing_paths = sorted(missing_paths)
                for pathIterator in missing_paths:
                   printAndOrLog('{}'.format(pathIterator,log))

        if fixedRenameList:
            if ((self.fix == 2) or (self.fix == 3)) and (self.verbosity >= 1):
                if (len(fixedRenameList) == 1):
                    printAndOrLog('1 filename fixed:',log)
                else:
                    printAndOrLog('{} filenames fixed:'.format(fixedRenameCounter),log)

                for i in range(0, fixedRenameCounter):
                    printAndOrLog('  \'{}\' to \'{}\''.format(fixedRenameList[i][0],fixedRenameList[i][1]),log)
       
        if fixedPropertiesList:
            if ((self.fix == 2) or (self.fix == 3)) and (self.verbosity >= 1):
                if (len(fixedPropertiesList) == 1):
                    printAndOrLog('1 file property fixed:',log)
                else:
                    printAndOrLog('{} file properties fixed:'.format(fixedPropertiesCounter),log)

                for i in range(0, fixedPropertiesCounter):
                    printAndOrLog('  Added missing access or modification timestamp to {}'.format(fixedPropertiesList[i][0]),log)
            
    def handle_unknown_path(self, cur, new_path, new_mtime, new_hash, paths, hashes, test, log):
        """Either add a new entry to the database or update the existing entry
        on rename.
        'cur' is the database cursor. 'new_path' is the new Unicode path.
        'paths' are Unicode paths seen on disk during this run of Bitrot.
        'hashes' is a dictionary selected from the database, keys are hashes, values
        are sets of Unicode paths that are stored in the DB under the given hash.
        Returns 'new_path' if the entry was indeed new or the 'old_path' (e.g.
        outdated path stored in the database for this hash) if there was a rename.
        """

        for old_path in hashes.get(new_hash, ()):
            if old_path not in paths:
                # File of the same hash used to exist but no longer does.
                # Let's treat 'new_path' as a renamed version of that 'old_path'.
                if (test == 0):
                    cur.execute('UPDATE bitrot SET mtime=?, path=?, timestamp=? WHERE path=?',(new_mtime, new_path, ts(), old_path),)
                return old_path
        else:
            # Either we haven't found 'new_sha1' at all in the database, or all
            # currently stored paths for this hash still point to existing files.
            # Let's insert a new entry for what appears to be a new file.
            try:
                if (test == 0):
                    cur.execute('INSERT INTO bitrot VALUES (?, ?, ?, ?)',(new_path, new_mtime, new_hash, ts()),)
            except Exception as e:
                printAndOrLog("Could not save hash: \'{}\'. Received error: {}".format(new_path, e),log)
            return new_path

def get_absolute_path(log=True, directory=b'.', ext=b'db'):
    """Compose the path to the selected bitrot file."""
    try:
        directory = os.fsencode(directory)
        ext = os.fsencode(ext)
        abspath = os.path.join(directory, b'.bitrot.' + ext)
    except UnicodeEncodeError:
        printAndOrLog("Warning: cannot encode file name: {}".format(path), log, sys.stderr)
        raise BitrotException("Warning: cannot encode file name: {}".format(path))
    except Exception as e:
        printAndOrLog("Could not get absolute path of file: \'{}\'. Received error: {}".format(directory, e),log)
        raise BitrotException("Could not open integrity file: \'{}\'. Received error: {}".format(directory, e))   

    return abspath

def get_relative_path(directory=b'.', log=True):
    relative_path = os.path.relpath(directory)
    try:
        relative_path = relative_path.decode(FSENCODING)
    except UnicodeDecodeError:
        printAndOrLog("Warning: cannot decode file name: {}".format(path), log, sys.stderr)
        raise BitrotException("Warning: cannot decode file name: {}".format(path))

    if (_platform == "linux" or _platform == "linux2"):
       relative_path = os.path.join('.',relative_path)
    elif (_platform == "win32" or _platform == "win64"):
        relative_path = os.path.join('.\\',relative_path)
    elif (_platform == "darwin"):
        printAndOrLog("Unsupported operating system.", log, sys.stderr)
        raise BitrotException("Unsupported operating system.")
    else:
        printAndOrLog("Unsupported operating system.", log, sys.stderr)
        raise BitrotException("Unsupported operating system.")
    return relative_path

def stable_sum(log=True, bitrot_db=None):
    """Calculates a stable SHA512 of all entries in the database.

    Useful for comparing if two directories hold the same data, as it ignores
    timing information."""
    if bitrot_db is None:
        bitrot_db = get_absolute_path(log, SOURCE_DIR_PATH,'db')
        try:
            bitrot_db = bitrot_db.decode(FSENCODING)
        except UnicodeDecodeError:
            printAndOrLog("Warning: cannot decode file name: {}".format(path), log, sys.stderr)
            raise BitrotException("Warning: cannot decode file name: {}".format(path))
        if not os.path.exists(bitrot_db):
            print("Database {} does not exist. Cannot calculate sum.".format(bitrot_db))
            exit()
    digest = hashlib.sha512()
    conn = get_sqlite3_cursor(bitrot_db, copy=False, log=log)
    cur = conn.cursor()
    cur.execute('SELECT hash FROM bitrot ORDER BY path')
    row = cur.fetchone()
    while row:
        digest.update(row[0].encode('ascii'))
        row = cur.fetchone()
    return digest.hexdigest()

def check_sha512_integrity(chunk_size=DEFAULT_CHUNK_SIZE, verbosity=1, log=True):
    sha512_path = get_absolute_path(log, SOURCE_DIR_PATH,ext=b'sha512')
    bitrot_db_path = get_absolute_path(log, SOURCE_DIR_PATH,'db')
    try:
        sha512_path = sha512_path.decode(FSENCODING)
    except UnicodeDecodeError:
        printAndOrLog("Warning: cannot decode file name: {}".format(path), log, sys.stderr)
        raise BitrotException("Warning: cannot decode file name: {}".format(path))

    try:
        bitrot_db_path = bitrot_db_path.decode(FSENCODING)
    except UnicodeDecodeError:
        printAndOrLog("Warning: cannot decode file name: {}".format(path), log, sys.stderr)
        raise BitrotException("Warning: cannot decode file name: {}".format(path))

    if not os.path.exists(sha512_path):
        return
    if not os.path.exists(bitrot_db_path):
        return

    if verbosity:
        printAndOrLog('Checking bitrot.db integrity...\n',log)
       
    try:
        with open(sha512_path, 'rb') as f:
            old_sha512 = f.read().strip()
            old_sha512 = old_sha512.decode()
            f.close()
    except Exception as e:
        printAndOrLog("Could not open integrity file: \'{}\'. Received error: {}".format(sha512_path, e),log)
        raise BitrotException("Could not open integrity file: \'{}\'. Received error: {}".format(sha512_path, e))   

    try:
        new_sha512 = integrityHash(bitrot_db_path, chunk_size, "SHA512")

    except Exception as e:
        printAndOrLog("Could not open database file: \'{}\'. Received error: {}".format(bitrot_db_path, e),log)
        raise BitrotException("Could not open database file: \'{}\'.".format(bitrot_db_path))   

    if new_sha512 != old_sha512:
        if len(old_sha512) == 128:
            printAndOrLog(
                "\nError: SHA512 of the database file \'{}\' is different, bitrot.db might "
                "be corrupt.".format(bitrot_db_path),log)
        else:
            printAndOrLog(
                "\nError: SHA512 of the database file \'{}\' is different, but bitrot.sha512 "
                "has a suspicious length. It might be corrupt.".format(bitrot_db_path),log)
        printAndOrLog("If you'd like to continue anyway, delete the .bitrot.sha512 file and try again.",log)
        printAndOrLog("bitrot.db integrity check failed, cannot continue.",log)

        raise BitrotException(3, 'bitrot.db integrity check failed, cannot continue.',)

def update_sha512_integrity(chunk_size=DEFAULT_CHUNK_SIZE, verbosity=1, log=True):
    sha512_path = get_absolute_path(log, SOURCE_DIR_PATH,ext=b'sha512')
    bitrot_db_path = get_absolute_path(log, SOURCE_DIR_PATH,'db')
    # except IOError as e:
    #     if e.errno == errno.EACCES:
    try:
        sha512_path= sha512_path.decode(FSENCODING)
    except UnicodeDecodeError:
        printAndOrLog("Warning: cannot decode file name: {}".format(path), log, sys.stderr)
        raise BitrotException("Warning: cannot decode file name: {}".format(path))
    try:
        bitrot_db_path = bitrot_db_path.decode(FSENCODING)
    except UnicodeDecodeError:
        printAndOrLog("Warning: cannot decode file name: {}".format(path), log, sys.stderr)
        raise BitrotException("Warning: cannot decode file name: {}".format(path))

    if not os.path.exists(bitrot_db_path):
        printAndOrLog("Could not open database file: \'{}\'.".format(bitrot_db_path),log)
        raise BitrotException("Could not open database file: \'{}\'.".format(bitrot_db_path))
    if not os.path.exists(sha512_path):
           old_sha512 = 0
    else:
        try:
            with open(sha512_path, 'rb') as f:
                old_sha512 = f.read().strip()
                old_sha512 = old_sha512.decode()
                f.close()
        except Exception as e:
            printAndOrLog("Could not open integrity file: \'{}\'. Received error: {}".format(sha512_path, e),log)
            raise BitrotException("Could not open integrity file: \'{}\'. Received error: {}".format(sha512_path, e))   
        except UnicodeDecodeError:
            printAndOrLog("Warning: cannot decode old SHA512 value: {}".format(sha512_path), log, sys.stderr)
            raise BitrotException("Warning: cannot decode old SHA512 value: {}".format(sha512_path))
    try:
        new_sha512 = integrityHash(bitrot_db_path, chunk_size, "SHA512")
    except Exception as e:
        printAndOrLog("Could not open database file: \'{}\'. Received error: {}".format(bitrot_db_path, e),log)
        raise BitrotException("Could not open database file: \'{}\'. Received error: {}".format(bitrot_db_path, e))

    if new_sha512 != old_sha512:
        if verbosity:
            printAndOrLog('Updating bitrot.sha512...',log)
        try:
            with open(sha512_path, 'wb') as f:
                f.write(str.encode(new_sha512))
                f.close()
        except Exception as e:
            printAndOrLog("Could not write integrity file: \'{}\'. Received error: {}".format(sha512_path, e),log)
            raise BitrotException("Could not write integrity file: \'{}\'. Received error: {}".format(sha512_path, e))   

def recordTimeElapsed(startTime=0):
    elapsedTime = (time.time() - startTime)  
    if (elapsedTime > 86400):
        elapsedTime /= 86400
        # if (elapsedTime >= 1.0) and (elapsedTime < 1.1):
        #     units = " days"
        # else:
        units = "days"

    elif (elapsedTime > 3600):
        elapsedTime /= 3600
        # if (elapsedTime >= 1.0) and (elapsedTime < 1.1):
        #     units = " hours"
        # else:
        units = "hr"

    elif (elapsedTime > 60):
        elapsedTime /= 60
        # if (elapsedTime >= 1.0) and (elapsedTime < 1.1):
        #     units = " minutes"
        # else:
        units = "min"

    else:
        # if (elapsedTime >= 1.0) and (elapsedTime < 1.1):
        #     units = " seconds"
        # else:
        units = "sec"

    return "{:.1f}".format(elapsedTime) + units
def main():
    run_from_command_line()
    
def run_from_command_line():
    global FSENCODING
    global SOURCE_DIR
    global DESTINATION_DIR
    global SOURCE_DIR_PATH
    SOURCE_DIR='.'
    parser = argparse.ArgumentParser(prog='bitrot')
    parser.add_argument(
        '-l', '--follow-links', type=str2bool, nargs='?', const=True, default=False,
        help='follow symbolic links and store target files\' hashes. Once '
             'a path is present in the database, it will be checked against '
             'changes in content even if it becomes a symbolic link. In '
             'other words, if you run \'bitrot -l\', on subsequent runs '
             'symbolic links registered during the first run will be '
             'properly followed and checked even if you run without \'-l\'.')
    parser.add_argument(
        '--sum', action='store_true',
        help='using only the data already gathered, return a SHA-512 sum '
             'of hashes of all the entries in the database. No timestamps '
             'are used in calculation.')
    parser.add_argument(
        '--version', action='version',
        version='%(prog)s {}.{}.{}'.format(*VERSION))
    parser.add_argument(
        '--commit-interval', type=float, default=DEFAULT_COMMIT_INTERVAL,
        help='min time in seconds between commits '
             '(0 commits on every operation).')
    parser.add_argument(
        '-w', '--workers', type=int, default=os.cpu_count(),
        help='run this many workers (use -w1 for slow magnetic disks)')
    parser.add_argument(
        '--chunk-size', type=int, default=DEFAULT_CHUNK_SIZE,
        help='read files this many bytes at a time.')
    parser.add_argument(
        '--fsencoding', default='',
        help='override the codec to decode filenames, otherwise taken from '
             'the LANG environment variables.')
    parser.add_argument(
        '-i', '--include-list', default='',
        help='only read the files listed in this file.')
        # .\Directory\1.hi
    parser.add_argument(
        '-t', '--test', default=0,
        help='Level 0: normal operations.\n'
        'Level 1: Just test against an existing database. Doesn\'t update anything.\n.'
        'Level 2: Doesnt compare dates, only hashes. No timestamps are used in the calculation. Doesn\'t update anything.\n'
        'You can compare to another directory using --destination.')
    parser.add_argument(
        '-a', '--algorithm', default='SHA512',
        help='Specifies the hashing algorithm to use.')
    parser.add_argument(
        '-r','--recent', default=0,
        help='Only deal with files < X days old.')
    parser.add_argument(
        '-x', '--exclude-list', default='',
        help="don't read the files listed in this file - wildcards are allowed.")
        #Samples: 
        # *DirectoryA
        # DirectoryB*
        # DirectoryC
        # *DirectoryD*
        # *FileA
        # FileB*
        # FileC
        # .\RelativeDirectoryE\*
        # .\RelativeDirectoryF\DirectoryG\*
        # *DirectoryH\DirectoryJ\*
        # .\RelativeDirectoryK\DirectoryL\FileD
        # .\RelativeDirectoryK\DirectoryL\FileD*
        # *DirectoryM\DirectoryN\FileE.txt
        # *DirectoryO\DirectoryP\FileF*
    parser.add_argument(
        '-v', '--verbose', default=1,
        help='Level 0: Don\'t print anything besides checksum errors.\n'
        'Level 1: Normal amount of verbosity.\n'
        'Level 2: List missing entries.\n'
        'Level 3: List missing, fixed, new, renamed, and updated entries.\n'
        'Level 4: List missing, fixed, new, renamed, updated entries, and excluded files.\n'
        'Level 5: List missing, fixed, new, renamed, updated entries, excluded files, and existing files\n.')
    # parser.add_argument(
    #     '-n', '--normalize', action='store_true',
    #     help='Only allow one unique normalized file into the DB at a time.')
    parser.add_argument(
        '-e', '--email', type=str2bool, nargs='?', const=True, default=True,
        help='Email file integrity errors')
    parser.add_argument(
        '--hidden', type=str2bool, nargs='?', const=True, default=True,
        help='Includes hidden files')
    parser.add_argument(
        '-g', '--log', default=1,
        help='logs activity')
    parser.add_argument(
        '--sfv', default='',
        help='Also generates an MD5 or SFV file when given either of these as a parameter')
    parser.add_argument(
        '-f', '--fix', default=0,
        help='Level 0: will not check for problem files.\n'
        'Level 1: Will report files that have missing access and modification timestamps.\n'
        'Level 2: Fixes files that have missing access and modification timestamps.\n'
        'Level 3: Will report files that have invalid characters.\n'
        'Level 4: Fixes files by removing invalid characters. NOT RECOMMENDED.\n'
        'Level 5: Will report files that have missing access and modification timestamps and invalid characters.\n'
        'Level 6: Fixes files by removing invalid characters and adding missing access and modification times. NOT RECOMMENDED.')
    parser.add_argument(
        '-s', '--source', default='',
        help="Root of source folder. Default is current directory.")
    parser.add_argument(
        '-d', '--destination', default='',
        help="Root of destination folder. Default is current directory.")

    queuedMessages = []
    args = parser.parse_args()
    log = args.log


    verbosity = int(args.verbose)

    try:
        if not args.source:
            SOURCE_DIR = '.'
            # if verbosity:
            #     printAndOrLog('Using current directory for file list.',args.log)
        else:
            if (os.path.isdir(args.source) == True):
                os.chdir(args.source)
                SOURCE_DIR_PATH = args.source
            #     if verbosity:
            #         printAndOrLog('Source directory \'{}\'.'.format(args.source),args.log)
            # else:
            #     printAndOrLog("Invalid Source directory: \'{}\'.\nExiting.".format(args.source),log) 
            #     exit()
    except Exception as err:
            SOURCE_DIR = '.'
            # if verbosity:
            #     printAndOrLog("Invalid source directory: \'{}\'. Received error: {}. \nExiting.".format(args.source, err),args.log)
            #     exit()


    if (verbosity and log):
        writeToLog(log, '\n=============================\n')
        writeToLog(log, 'Log started at ')
        writeToLog(log, datetime.datetime.now().strftime("%Y-%m-%d %H:%M"))

    if (verbosity == 2):
        printAndOrLog("Verbosity option selected: {}. List missing entries.".format(args.verbose),log)
    elif (verbosity == 3):
        printAndOrLog("Verbosity option selected: {}. List missing, fixed, new, renamed, and updated entries.".format(args.verbose),log)
    elif (verbosity == 4):
        printAndOrLog("Verbosity option selected: {}. List missing, fixed, new, renamed, updated entries, and excluded files.".format(args.verbose),log)
    elif (verbosity == 5):
        printAndOrLog("Verbosity option selected: {}. List missing, fixed, new, renamed, updated entries, excluded files, and existing files.".format(args.verbose),log)
    elif not (verbosity == 0) and not (verbosity == 1):
        printAndOrLog("Invalid verbosity option selected: {}. Using default level 1.".format(args.verbose),log)
        verbosity = 1

    try:
        if not args.source:
            #SOURCE_DIR = '.'
            if verbosity:
                printAndOrLog('Using current directory for file list.',args.log)
        else:
            if (os.path.isdir(args.source) == True):
                # os.chdir(args.source)
                # SOURCE_DIR_PATH = args.source
                if verbosity:
                    printAndOrLog('Source directory \'{}\'.'.format(args.source),args.log)
            else:
                printAndOrLog("Invalid Source directory: \'{}\'.\nExiting.".format(args.source),log) 
                exit()
    except Exception as err:
            # SOURCE_DIR = '.'
            if verbosity:
                printAndOrLog("Invalid source directory: \'{}\'. Received error: {}. \nExiting.".format(args.source, err),args.log)
                exit()  

    log_path = get_absolute_path(log, SOURCE_DIR_PATH,ext=b'log')
    
    if args.sum:
        try:
            printAndOrLog("Hash of {} is \n{}".format(SOURCE_DIR_PATH,stable_sum(log)),log)
            exit()
        except RuntimeError as e:
            printAndOrLog(str(e), log, sys.stderr)


    DESTINATION_DIR = SOURCE_DIR

    try:
        test = int(args.test)
        if (verbosity):
            if (test == 0):
                queuedMessages.append("Testing-only mode disabled.")
            elif (test == 1):
                queuedMessages.append("Just testing against an existing database. Won\'t update anything.")
            elif (test == 2):
                queuedMessages.append("Won\'t compare dates, only hashes. Won\'t update anything.")
            else:
                queuedMessages.append("Invalid test option selected: " + args.test +". Using default level 0: testing-only disabled.")
                test = 0
    except Exception as err:
        queuedMessages.append("Invalid test option selected: " + args.test +". Using default level 0: testing-only disabled.")
        test = 0

    if not args.destination:
        if verbosity:
            printAndOrLog('Using current directory for destination file list.',log)
    else:
        if (test == 0 and args.destination):
            if verbosity:
                printAndOrLog("Setting destination only works in testing mode. Please see --test. \nExiting.",log)
                exit()
        else:
            if (os.path.isdir(args.destination) == True):
                DESTINATION_DIR = args.destination
                if verbosity:
                    printAndOrLog('Destination directory \'{}\'.'.format(args.destination),log)
            else:
                printAndOrLog("Invalid Destination directory: \'{}\'.\nExiting.".format(args.destination),log) 
                exit()

    for message in queuedMessages:
        printAndOrLog(message,log)
    if queuedMessages:
        del queuedMessages
        gc.collect()

    include_list = []
    if args.include_list:
        if verbosity:
            printAndOrLog('Opening file inclusion list at \'{}\'.'.format(args.include_list),log)
        try:
            #include_list = [line.rstrip('\n').encode(FSENCODING) for line in open(args.include_list)]
            with open(args.include_list) as includeFile:
                for line in includeFile:
                    try:
                        line = line.rstrip('\n')
                    except UnicodeEncodeError:
                        printAndOrLog("Warning: cannot encode file name: {}".format(path), log, sys.stderr)
                        raise BitrotException("Warning: cannot encode file name: {}".format(path))
                    include_list.append(line)
                includeFile.close() # should be harmless if include_list == sys.stdin

        except Exception as err:
            printAndOrLog("Invalid inclusion list specified: \'{}\'. Not using an inclusion list. Received error: {}".format(args.include_list, err),log)
            include_list = []
    else:
        include_list = []
    exclude_list = []
    if args.exclude_list:
        if verbosity:
            printAndOrLog('Opening file exclusion list at \'{}\'.'.format(args.exclude_list),log)
        try:
            # exclude_list = [line.rstrip('\n').encode(FSENCODING) for line in open(args.exclude_list)]
            with open(args.exclude_list) as excludeFile:
                for line in excludeFile:
                    try:
                        line = line.rstrip('\n')
                    except UnicodeEncodeError:
                        printAndOrLog("Warning: cannot encode file name: {}".format(path), log, sys.stderr)
                        raise BitrotException("Warning: cannot encode file name: {}".format(path))
                    exclude_list.append(line)
                excludeFile.close() # should be harmless if include_list == sys.stdin
        except Exception as err:
            printAndOrLog("Invalid exclusion list specified: \'{}\'. Not using an exclusion list. Received error: {}".format(args.exclude_list, err),log)
            exclude_list = []
    else:
        exclude_list = []

    try:
        workers = int(args.workers)
        if (verbosity):
            if (workers <= 0 or workers > 61):
                printAndOrLog('{} workers selected. Worker count must be between 1-61. Using the default of 1.'.format(args.workers),log)
                workers = 1
            else:
                printAndOrLog('Using {} workers.'.format(args.workers),log)
    except Exception as err:
        printAndOrLog('{} workers selected. Worker count must be between 1-61. Using the default of 1.'.format(args.workers),log)
        workers = 1

    try:
        chunk_size = int(args.chunk_size)
        if (verbosity):
            if (chunk_size <= 0):
                printAndOrLog('{} chunk size selected. Chunk size must be > 0. Using the default of 1.'.format(args.chunk_size),log)
                workers = 1
            else:
                printAndOrLog('Using chunk size of {}.'.format(args.chunk_size),log)
    except Exception as err:
        printAndOrLog('Chunk size {} selected. Chunk size must be > 0. Using the default of 1.'.format(args.chunk_size),log)
        workers = 1

    try:
        commit_interval = int(args.commit_interval)
        if (verbosity):
            if (commit_interval <= 0):
                printAndOrLog('{} commit interval selected. Commit interval must be > 0. Using the default of {}.'.format(args.commit_interval, DEFAULT_COMMIT_INTERVAL),log)
                commit_interval = DEFAULT_COMMIT_INTERVAL
            else:
                printAndOrLog('Using a commit interval of {}.'.format(args.commit_interval),log)
    except Exception as err:
        printAndOrLog('{} commit interval selected. Commit interval must be > 0. Using the default of {}.'.format(args.commit_interval, DEFAULT_COMMIT_INTERVAL),log)
        commit_interval = DEFAULT_COMMIT_INTERVAL

    #combined = '\t'.join(hashlib.algorithms_available)
    #if (args.algorithm in combined):

    #word_to_check = args.algorithm
    #wordlist = hashlib.algorithms_available
    #result = any(word_to_check in word for word in wordlist)

    #algorithms_available = hashlib.algorithms_available
    #search = args.algorithm
    #result = next((True for algorithms_available in algorithms_available if search in algorithms_available), False)
    if (isValidHashingFunction(stringToValidate=args.algorithm) == True):
        algorithm = args.algorithm.upper()
        if (verbosity):
            printAndOrLog('Using {} for hashing functions.'.format(algorithm),log)
    else:
        if (verbosity):
            printAndOrLog("Invalid hashing function specified: {}. Using default {}.".format(args.algorithm,DEFAULT_HASH_FUNCTION),log)
            algorithm = DEFAULT_HASH_FUNCTION

    sfv_path = get_absolute_path(log, SOURCE_DIR_PATH,ext=b'sfv')
    md5_path = get_absolute_path(log, SOURCE_DIR_PATH,ext=b'md5')

    try:
        os.remove(sfv_path)
    except Exception as err:
        pass
    try:
        os.remove(md5_path)
    except Exception as err:
        pass
    if (args.sfv):
        if (args.sfv.upper() == "MD5" or args.sfv.upper() == "SFV"): 
            sfv = args.sfv.upper() 
            if (verbosity):
                printAndOrLog('Will generate an {} file.'.format(sfv),log) 
        else:
            if (verbosity):
                printAndOrLog("Invalid SFV/MD5 filetype specified: {}. Will not generate any additional file.".format(args.sfv),log)
            sfv = ""
    else:
        sfv = ""

    try:
        recent = int(args.recent)
        if (recent):
            if (verbosity):
                printAndOrLog("Only processing files <= {} days old.".format(args.recent),log)
        elif (recent == 0):
            if (verbosity):
                printAndOrLog("Processing all files, not just recent ones.",log)
        else:
            if (verbosity):
                printAndOrLog("Invalid recent option selected: {}. Processing all files, not just recent ones.".format(args.recent),log)
            recent = 0
    except Exception as err:
        printAndOrLog("Invalid recent option selected: {}. Processing all files, not just recent ones.".format(args.recent),log)
        recent = 0

    email = args.email 
    try:
        if (email == True):
            if (verbosity):
                printAndOrLog("Sending emails on errors.".format(args.email),log)
        elif (email == False):
            if (verbosity):
                printAndOrLog("Will not sending emails on errors.".format(args.email),log)
        else:
            if (verbosity):
                printAndOrLog("Invalid email option selected: {}. Sending emails on errors.".format(args.email),log)
                email = True
    except Exception as err:
        printAndOrLog("Invalid email option selected: {}. Sending emails on errors.".format(args.email),log)
        email = True

    hidden = args.hidden 
    try:
        if (hidden == True):
            if (verbosity):
                printAndOrLog("Including hidden files.".format(args.hidden),log)
        elif (hidden == False):
            if (verbosity):
                printAndOrLog("Will not include hidden files.".format(args.hidden),log)
        else:
            if (verbosity):
                printAndOrLog("Invalid hidden option selected: {}. Including hidden files.".format(args.hidden),log)
                hidden = True
    except Exception as err:
        printAndOrLog("Invalid hidden option selected: {}. Including hidden files.".format(args.hidden),log)
        hidden = True

    follow_links = args.follow_links 
    try:
        if (follow_links == True):
            if (verbosity):
                printAndOrLog("Following symlinks".format(args.follow_links),log)
        elif (follow_links == False):
            if (verbosity):
                printAndOrLog("Will not follow symlinks".format(args.follow_links),log)
        else:
            if (verbosity):
                printAndOrLog("Invalid email option selected: {}. Will not follow synlinks".format(args.follow_links),log)
                follow_links = True

    except Exception as err:
        printAndOrLog("Invalid email option selected: {}. Will not follow synlinks".format(args.follow_links),log)
        follow_links = True
 
 
    # normalize=False
    # if (args.normalize):
    #     printAndOrLog("Only allowing one similarly named normalized file into the database.",log)
    #     normalize=True

    try:
        fix = int(args.fix)
        if (fix == 0):
            if (verbosity):
                printAndOrLog("Will not check problem files.",log)
        elif (fix == 1):
            if (verbosity):
                printAndOrLog("Fixes files that have missing access and modification timestamps. To report only, also use -t or --test",log)
        elif (fix == 2):
            if (verbosity):
                printAndOrLog("Fixes files by removing invalid characters. To report only, also use -t or --test. NOT RECOMMENDED.",log)
        elif (fix == 3):
            if (verbosity):
                printAndOrLog("Fixes files by removing invalid characters and adding missing access and modification times.  To report only, also use -t or --test. NOT RECOMMENDED.",log)
        else:
            if (verbosity):
                printAndOrLog("Invalid test option selected: {}. Using default level; will not report files that have missing access and modification timestamps and invalid characters.".format(args.fix),log)
                fix = 0
    except Exception as err:
        printAndOrLog("Invalid test option selected: {}. Using default level; will not report files that have missing access and modification timestamps and invalid characters.".format(args.fix),log)
        fix = 0

    bt = Bitrot(
        verbosity = verbosity,
        algorithm = algorithm,
        test = test,
        recent = recent,
        email = email,
        log = log,
        hidden = hidden,
        follow_links = follow_links,
        commit_interval = commit_interval,
        chunk_size = chunk_size,
        workers=workers,
        include_list = include_list,
        exclude_list = exclude_list,
        sfv = sfv,
        fix = fix,
        # normalize=normalize,
    )
    if args.fsencoding:
        FSENCODING = args.fsencoding

    try:
        bt.run()
    except BitrotException as bre:
        printAndOrLog('Error: {}'.format(bre.args[1]),log)
        sys.exit(bre.args[0])

if __name__ == '__main__':
    freeze_support()
    run_from_command_line()
