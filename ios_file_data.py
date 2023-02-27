# Script by: DarkSplash
# Last edited: 02/24/2023

# This script holds data about the new IOS file to be downloaded.
# The file can be located on any server that can SCP files to your switch.
# The FileServerPath variable is the folder that the file itself it located in
# with no starting or ending slashes, and IOSFile is the name of the file itself.
# IOSSize is how many bytes the new IOS bin file is. The Linux commands
# ls -al or ll should be two easy ways of checking for file size.
# md5sum {filename} is the Linux command on how to get the MD5 value.
# Look at the README for more detailed instructions.

# Example configuration:
# IOSVersion = "16.09.01"                       (XX.XX.XX)
# FileServerIP = "192.168.0.50"                 (IP address of file server)
# FileServerPath = "srv/fileshare"              (Path to file directory with no starting or ending forward slashes)
# IOSFile = "cat9k_iosxe.16.09.01.SPA.bin"      (file to download in FileServerPath directory)
# IOSMD5 = "258fb60ca843a2db78d8dba5a9f64180"   (MD5 hash of file to download)
# IOSSize = 699968920                           (File size in bytes)
################################################################################

IOSVersion = ""
FileServerIP = ""
FileServerPath = ""
IOSFile = ""
IOSMD5 = ""
IOSSize = 0