# Script by: DarkSplash
# Last edited: 02/27/2023

# This script is designed to upgrade the IOS version of a c9000 IOS or IOS-XE switch.
# Currently the script looks for a file located somewhere in a specified fileserver directory,
# downloads it, runs all the install commands, commits the upgrade, and then checks to make sure
# all switches in the host list were successfully upgraded. Additionally, at the end of the script,
# there is the option to run "install remove inactive" on all of the switches to remove any old
# IOS files that are no longer used after the update to free up space on the switches.


from datetime import datetime
import getpass
import ios_file_data                                    # Script to hold IOS file variables
import logging
from nornir import InitNornir
from nornir.core.filter import F
from nornir.core.task import Task, Result
from nornir_napalm.plugins.tasks import napalm_get
from nornir_netmiko.tasks import netmiko_send_command
from nornir_netmiko.tasks import netmiko_send_config
from nornir_netmiko.tasks import netmiko_save_config
import swan_logger                                      # Custom written logger script, look at commandLogger() or script for more details
import time


# Packageless Terminal Colors: https://stackoverflow.com/a/21786287
RED = "\x1b[1;31;40m"
GREEN = "\x1b[1;32;40m"
CLEAR = "\x1b[0m"



# https://nornir.discourse.group/t/using-getpass-getpass-instead-of-pre-filled-password/78 (Now a dead site, RIP my sweet prince)
# This man is a god amongst us mere mortals, how to set Nornir credentials on runtime
################################################################################
def nornir_set_creds(nr, username=None, password=None):
    if not username:
        username = input("Enter username: ")
    if not password:
        password = getpass.getpass()

    for host_obj in nr.inventory.hosts.values():
        host_obj.username = username
        host_obj.password = password



# NEW IOS DATA
# Function populates global variables pertaining to the new IOS image the switches will be updating to
################################################################################
def newIOSData():
    while True:
        newIOSVersion = ios_file_data.IOSVersion
        newFileServerIP = ios_file_data.FileServerIP
        newFileServerPath = ios_file_data.FileServerPath
        newIOSFile = ios_file_data.IOSFile
        newIOSMD5 = ios_file_data.IOSMD5
        newIOSSize = ios_file_data.IOSSize

        versionChecker = newIOSVersion.split(".")       # Making sure version is formatted properly
        for substring in versionChecker:
            if len(substring) != 2:                     # Each substring should be of length 2
                print(f"\nIOS version {RED}{newIOSVersion}{CLEAR} misformatted in ios_file_data.py, please follow XX.XX.XX notation.\n")
                raise SystemExit(0)                     # Exiting script on incorrectly formatted IOS version
        
        if newFileServerPath[0] == "/":
            print(f"\nFileserver path {RED}{newFileServerPath}{CLEAR} starts with a forward slash")
            print("Remove the forward slash from FileServerPath in ios_file_data.py and run this script again.\n")
            raise SystemExit(0)                         # Exiting script on incorrectly formatted download server path
        elif newFileServerPath[-1] == "/":
            print(f"\nFileserver path {RED}{newFileServerPath}{CLEAR} ends with a forward slash")
            print("Remove the forward slash from FileServerPath in ios_file_data.py and run this script again.\n")
            raise SystemExit(0)                         # Exiting script on incorrectly formatted download server path

        print(f"\nNew IOS Version: {newIOSVersion}")
        print(f"New Fileserver IP: {newFileServerIP}")
        print(f"New Fileserver Path: {newFileServerPath}")
        print(f"New IOS File: {newIOSFile}")
        print(f"New IOS MD5: {newIOSMD5}")
        print(f"New IOS Size: {newIOSSize}")

        while True:
            answer = input("\n\nDo these values look correct (yes or no)?\n")
            if "yes" in answer.lower():
                print()
                return newIOSVersion, newFileServerIP, newFileServerPath, newIOSFile, newIOSMD5, newIOSSize
            elif "no" in answer.lower():
                print("\nVariable data is changed in ios_file_data.py")
                raise SystemExit(0)                     # Exiting script on incorrect data
            else:
                print("Please either answer \"yes\" or \"no\".\n")



# NORNIR INIT
# Function explititly made to solve bugs in checkAliveReboot2(), look there for why
# this function was made.  This is now the main function used to initialize nornir objects
# instead of using InitNornir(), just moved the code that used to exist in the
# preconfiguration portion of main() to create the nornir object and made it
# so you can create an object whenever you want.  This function only gets passed
# the username and password parameters when a new nornir object is being initialized
# after the old nornir object has timed out/stopped responding after a reboot.
################################################################################
def nornirInit(configFile, username=None, password=None):
    nr = InitNornir(config_file=configFile)             # Initializing Nornir object
    
    if username is not None and password is not None:   # Portion of code for re-initializing nornir object, look at checkAliveReboot2() for more info
        nornir_set_creds(nr, username, password)
    else:
        nornir_set_creds(nr)

    print("\nFiltering to only INSTALL mode switches...\n")
    nr = nr.filter(F(groups__contains="install"))       # Install mode filter
    
    return nr


# CREDENTIAL GRABBER
# Function was made due to the bugs that were being encountered in checkAliveReboot2().
# To fix these bugs, reinitializing the nr object seemed to do the job, but requires
# a username and password each time it was made. Since the user already needed to manually
# enter in their credentials at the beginning, and nornir stores those values, I can just
# grab those already existing login credentials and recreate the nornir object.
# The "if username is not..." portion of nornirInit() is where this data is being passed to
################################################################################
def credentialGrabber(nr):
    username = ""                                       # Grabbing username and password so every recreation of the
    password = ""                                       # Nornir object doesn't prompt you for credentials
    for host in nr.inventory.hosts.values():
            username = host.username
            password = host.password
            break
    return username, password



# IS ALIVE TASK
# Shamelessly ripped code from the creator of netmiko (who also maintains nornir & napalm)
# https://github.com/nornir-automation/nornir/issues/493
# is_alive() checks to see if nornir can communicate with port 22 on a switch
################################################################################
def isAliveTask(task: Task) -> Result:
    napalm = task.host.get_connection("napalm", task.nornir.config)     # task.host is variable holding hosts.yaml variable name (not hostname)
    alive = napalm.is_alive()                                           # get_connection was passed napalm for its plugin to connect with and passed the current config variable of nornir
    return Result(host=task.host, result=alive)                         # This manages to create a napalm variable that you can run napalm functions off of



# CHECK ALIVE
# Checks dict made by napalm's is_alive() function
# Returns 1 if any of the switches are offline
################################################################################
def checkAlive(nr):
    print("Checking if switches are online...")
    output = nr.run(task=isAliveTask)

    for hostname in output:                             # Grabs the name of the inventory from hosts.yaml (Non-indented part of file) 
        result = output[hostname].result                # Unwrapping a single device's results out of nornir's weird dict-esque variable (AggregatedResult)
                                                        # NOTE: Both of these happen ALOT in other functions, so this will be the only comment about it

        if type(result) != dict:                        # Alive hosts are contained within a dict, whereas dead hosts are a string traceback
            print(f"{RED}{hostname}{CLEAR} does not appear to be online")
            return 1                                    # This super ugly block is due to is_alive() crashing this program due to non-alive hosts
        else:                                           # returning the string traceback of the error (thank you NAPALM, very cool!)
            if result['is_alive'] == False:             # No idea if this will ever be called, but here in case result doesnt throw a string traceback
                print(f"{RED}{hostname}{CLEAR} does not appear to be online")
                return 1
        
    print("All switches appear to be online\n")



# BUNDLE OR INSTALL
# Function looks at all hosts and determines if the boot mode is INSTALL mode or
# BUNDLE mode. If BUNDLE mode is detected, the function immediately exits out
# and reports what switches need to be removed from the host list for this script
# to properly work, as this script was written for switches in INSTALL mode.
################################################################################
def bundleOrInstall(nr):
    print("Checking what boot mode the switches use...")
    command = "show version"
    output = nr.run(netmiko_send_command, command_string=command)
    filterFlag = 0                                      # Flag used to warn users in main of the issues of running this script against bundle mode switches
    
    swan_logger.commandLogger(command, output, "STARTLOG")  # Start log banner being added
    swan_logger.commandLogger(command, output)          # Actually logging first command

    for hostname in output:                       
        result = output[hostname].result

        if "BUNDLE" in result:
            print(f"{RED}{hostname}{CLEAR} is configured to be in BUNDLE mode")
            filterFlag = 1
            
        elif "INSTALL" in result:
            print(f"{GREEN}{hostname}{CLEAR} is configured to be in INSTALL mode")
    print()
    return filterFlag



# CHECK AUTO UPGRADE
# Function iterates through hosts.yaml and looks to see if c9348s have
# the command "software auto-upgrade enable" as it is needed to upgrade all
# switches in a stack that are using INSTALL mode.
# Unique function to INSTALL mode script.
################################################################################
def checkAutoUpgrade(nr):
    print("Checking if \"software auto-upgrade enable\" is configured on switches")
    command = "sh run | i software auto"
    output = nr.run(netmiko_send_command, command_string=command)   # Looking if "software auto-upgrade enable" is in the running config

    swan_logger.commandLogger(command, output)

    for hostname in output:
        result = output[hostname].result

        if result == "":                                # When "software auto-upgrade enable" is not yet configured (blank string meaning the config wasnt found)
            print(f"{RED}{hostname}{CLEAR} is missing \"software auto-upgrade enable\" in running-config, adding...")
            filter = nr.filter(F(name=hostname))        # Creating a new nornir object that only has a single host which doesnt have software auto-upgrade enable configured
            filterResult = filter.run(netmiko_send_config, config_commands="software auto-upgrade enable")  # Adding the missing config
            filterResult2 = filter.run(netmiko_save_config)
            print("Configuration successfully added and saved!\n")
    print("All switches are configured with \"software auto-upgrade enable\"\n")



# SET IGNORE STARTUP CFG
# Function goes through and runs the command "no system ignore startupconfig switch all"
# on all switches. Done because if this is not set, after reboot, the switch will
# not load its configuration, taking it offline.
################################################################################
def setIgnoreStartupCfg(nr):
    print("Making sure the SWITCH_IGNORE_STARTUP_CFG register is set to 0")
    command = "no system ignore startupconfig switch all"

    output = nr.run(netmiko_send_config, config_commands=command)
    swan_logger.commandLogger(command, output)

    output2 = nr.run(netmiko_save_config)
    print("SWITCH_IGNORE_STARTUP_CFG has been set to 0\n")



# RESET BOOT VAR
# This is identical to removeBundleBoot() in the BUNDLE script. I have never needed
# to run this function and the script works fine without this function, but during
# code review, I was told that for IOS 17+, they for some reason now have you set 
# the boot var explicitly to packages.conf, even though you have never needed to
# do this previously. Function unsets the boot variable and then re-sets it to 
# packages.conf because Cisco says to...
################################################################################
def resetBootVar(nr):
    print("Resetting boot variable...")
    command = "no boot system"
    output = nr.run(netmiko_send_config, config_commands=command)
    swan_logger.commandLogger(command, output)

    command2 = "boot system flash:packages.conf"
    output2 = nr.run(netmiko_send_config, config_commands=command2)
    
    output3 = nr.run(netmiko_save_config)               # Boot variable on next reload only updates after saving config

    print("Boot variable has been reset to packages.conf!\n")



# GET SWITCH DATA
# Function iterates through hosts.yaml and grabs their hostnames and IOS versions,
# could change result["facts"]["hostname"] to result["facts"]["fqdn"] for a fully qualified name
# Try/Except added in for case where you dont wait for all hosts to come back online during restart
################################################################################
def getSwitchData(nr):
    print("Getting switch hostnames & IOS versions...")
    output = nr.run(napalm_get, getters="facts")
    switchHostnames = []
    switchIOSVersion = []

    for hostname in output:
        try:
            result = output[hostname].result
            name = result["facts"]["hostname"]
            switchHostnames.append(name)
        except Exception as e:
            print()
    
    for hostname in output:
        try:
            result = output[hostname].result
            substring = result["facts"]["os_version"]       # Selecting only the OS version portion of the napalm result
            x = substring.find("Version") + 8               # Finding starting location of version number string (8 characters after "Version")
            substring = substring[x:]
            y = substring.find(",")                         # Finding end index of version number string
            substring = substring[:y]                       # Trimming fluff
            switchIOSVersion.append(versionFormatter(substring))
        except Exception as e:
            print(f"Error gathering switch data, one or more switches probably offline")
    
    print("Complete!\n")
    return switchHostnames, switchIOSVersion



# GET FREE SPACE
# Function iterates through hosts.yaml and grabs the free space remaining in bytes
################################################################################
def getFreeSpace(nr):
    print("Getting remaining free space on switches...")
    command = "dir"
    output = nr.run(netmiko_send_command, command_string=command)
    switchFreeSpace = []

    swan_logger.commandLogger(command, output)

    for hostname in output:
        result = output[hostname].result
        lastLine = result.splitlines()[-1]              # Grabbing line with free space so filenames dont mess with substrings
        x = lastLine.find("(") + 1                      # Finding index of first parenthesis where free space starts
        substring = lastLine[x:]
        y = lastLine.find(" ")                          # Finding index of space after free space size
        size = int(substring[:y])                       # Trimming fluff and casting to int instead of str
        switchFreeSpace.append(size)

    print("Complete!\n")
    return switchFreeSpace



# IOS VERSION FORMATTER
# Function takes a string and sanatizes its format to match the .bin version number format (XX.XX.XX)
################################################################################
def versionFormatter(string):
    arr = string.split(".")                             # Splitting the string delimited by "." into three substrings
    counter = 0
    version = ""

    for x in arr:                                       # Taking each individual substring
        if len(x) != 2:                                 # If it is not 2 characters long, append a zero to the front
            x = "0" + x
        if counter < 2:                                 # If it is the first or second element, add a period after the substring
            version = version + x + "."
            counter = counter + 1
        elif counter == 2:                              # If it is the third element, just append the substring to the end
            version = version + x
    return version



# PRINT FORMATTER
# Function takes master switch array and makes a pretty string to print out
################################################################################
def printFormatter(arr, newIOSVer):
    maxHostname = 0                                     # Variables for max string lengths
    maxVersion = 0
    maxFreeSpace = 0
    maxNewVersion = len(newIOSVer)
    table = ""

    for element in arr:                                 # Finding max string length of each array element
        if maxHostname < len(element[0]):
            maxHostname = len(element[0])
        if maxVersion < len(element[1]):
            maxVersion = len(element[1])
        if maxFreeSpace < len(str(element[2])):         # Converting int to string to get length
            maxFreeSpace = len(str(element[2]))
    
    total = maxHostname + maxVersion + maxFreeSpace + maxNewVersion

    table += "HOSTNAME".ljust(maxHostname+2)            # Adding table headers
    table += "VERSION".ljust(maxVersion+2)
    table += "NEW VER.".ljust(maxNewVersion+2)
    table += "FREE SPACE".ljust(maxFreeSpace+2) + "\n"
    table += "#".ljust(total+8,"#") + "\n"              # Padding table seperator to split headers from data, +8 is from the +2's ^^^

    for element in arr:                                 # Printing out table data
        table += element[0].ljust(maxHostname+2)
        table += element[1].ljust(maxVersion+2)
        table += newIOSVer.ljust(maxNewVersion+2)
        table += str(element[2]).ljust(maxFreeSpace+2)
        table += "\n"
    print(table)



# SCP ESTIMATE
# Function estimates the amount of time the download will take based off a few tests
# fileSize input must be in bytes, speed is in kibibytes
################################################################################
def scpEstimate(fileName, fileSize):
    sec = round((fileSize / 409600), 2)
    minute = round((sec/60), 2)
    hour = round((sec/3600), 2)
    print(f"Assuming a download speed of 400 KiB, {fileName} will take {sec} seconds ({minute} minutes, {hour} hours) to transfer")



# READ TIMEOUT ESTIMATE
# Function returns an int that represents how many seconds netmiko will wait
# to see a certain string.  This function assumes an abysmal speed of 
# 250 kibibytes/sec, and even adds another 15 minutes as a safety net.
def readTimeoutEstimate(filesize):
    timeout = int(filesize/256000)                      # Calculating how many seconds download will take
    timeout = timeout + 900                             # Adding another 15 minutes to timeout
    return timeout



# CHECK FREE SPACE
# Function checks only on the switches that are missing the file if they have enough
# space to download the new .bin file. Returns 0 if they have space, returns 1 if one
# or more do not have space
################################################################################
def checkFreeSpace(arr, requiredSpace, missingFile):
    flag = 0

    print("\nChecking to ensure switches have enough room for the file...\n")
    for switches in arr:
        if switches[0] in missingFile:                  # Filtering to only look at switches who are missing the file
            if switches[2] < requiredSpace:
                flag = 1
                print(f"{RED}{switches[0]}{CLEAR} does not have enough free space for the new IOS .bin file")
                print(f"Switch Free Space - {switches[2]} < {requiredSpace} - IOS File Size\n")

    if flag == 1:
        print("One or more switches do not have enough space for the new IOS .bin file\n")
        return 1
    else:
        print("All switches have enough space for the new IOS .bin file\n")
        return 0



# MISSING FILE CHECKER
# Function checks to see if the passed file exists on the switches. Used once
# to check before the download, and once to insure files actually downloaded
# Returns a list of switch hostnames that are missing the file
################################################################################
def missingFileChecker(nr, filename):
    command = "dir | i " + filename                     # BUG: If you are checking for a file named "test" and there is a file already named "test2", this will erroneously report that "test" already exists. To fix just do better string comparisons
    output = nr.run(netmiko_send_command, command_string=command)    # Looking if the passed filename is in the flash
    missingFile = []                                    # List to hold all hostnames that do not have the new file

    swan_logger.commandLogger(command, output)

    print(f"Checking if switches have {filename}...")
    for hostname in output:                       
        result = output[hostname].result
        if result == "":
            print(f"{RED}{hostname}{CLEAR} does not have {filename} in it's flash")
            missingFile.append(hostname)                # Adding hostname
        else:
            print(f"{GREEN}{hostname}{CLEAR} has {filename} in it's flash")
    print()
    return missingFile



# SCP IOS BIN
# Function sends the bin file via SCP to all of the selected switches, 
# missingFile is what is returned by missingFileChecker() above, an array of
# only switches that are missing the desired file
################################################################################
def scpIOSBin(nr, ipAddress, folderPath, filename, filesize, missingFile):
    filter = nr.filter(F(name__in=missingFile))         # name__in filters by a list of hostnames, filter object is only switches that are missing the requested file

    fileUsername = input(f"Enter file server ({ipAddress}) username: ")
    filePassword = getpass.getpass()

    tempTime = datetime.now().strftime("%I:%M:%S %p")   # Listing out when download started
    print(f"\nBeginning SCP transfer... - {tempTime}")
    
    command = f"copy scp://{fileUsername}@{ipAddress}//{folderPath}/{filename} flash:/{filename}"
    output = filter.run(netmiko_send_command, command_string=command, expect_string=r'Destination filename', read_timeout=60)
    swan_logger.commandLogger(command, output, "STARTCOMMAND")

    output2 = filter.run(netmiko_send_command, command_string="", expect_string=r"Password", read_timeout=5)    # I have no idea why I need to pass a blank string before the password nor why you need a 5 second timeout delay, but you do
    swan_logger.commandLogger("", output2, "CONTINUECOMMAND")
    
    nornirLogger = logging.getLogger("nornir.core")
    nornirLogger.disabled = True
    output3 = filter.run(netmiko_send_command, command_string=filePassword, expect_string=r"copied", read_timeout=readTimeoutEstimate(filesize), cmd_verify=False)
    swan_logger.commandLogger("***DO NOT ACTUALY LOG PASSWORD***", output3, "ENDCOMMAND")
    nornirLogger.disabled = False

    print("Transfer completed!\n")
    
    for hostname in output3:
        result = output3[hostname].result               # Grabbing string containing how much time the transfer took
        x = result.find("copied in") + 10               # Getting starting string index of transfer time & speed 
        duration = result[x:]
        y = duration.find("/sec)") + 5                  # Getting ending string index of transfer time & speed
        duration = duration[:y]
        print(f"{GREEN}{hostname}{CLEAR} took {duration} to transfer {filename}")
    print()



# MD5 CHECKER
# Function checks the MD5 hash of the file on the switch after it has been downloaded
# Returns 1 if the hashes do not match
################################################################################
def MD5Checker(nr, filename, filesize, MD5):
    print("Checking MD5 hash (this may take a few minutes)...")
    command = "verify /md5 flash:" + filename
    output = nr.run(netmiko_send_command, command_string=command, read_timeout=readTimeoutEstimate(filesize))
    flag = 0                                            # Will be set to 1 if hashes dont match

    swan_logger.commandLogger(command, output)

    for hostname in output:
        result = output[hostname].result
        x = result.find(") =") + 4
        fileHash = result[x:]                           # Substringing MD5 portion of command output
        
        if fileHash.strip() == MD5.strip():             # Stripping newlines and other chars that will mess this up
            print(f"{GREEN}{hostname}{CLEAR}'s {filename} matches the given MD5")
        else:
            print(f"{RED}{hostname}{CLEAR}'s {filename} does not match the given MD5")
            print(f"{fileHash.strip()} =/= {MD5.strip()}\n")
            flag = 1
    return flag



# UPGRADE IOS
# Function that actually runs the upgrade commands on the switch. Starts off with 
# install add file flash:{filename} to expand the .bin file archive followed by
# install activate which is what actually changes configs and restarts the switch
################################################################################
def upgradeIOS(nr, filename):
    print("\nSaving switch config...")
    nr.run(netmiko_save_config)                                 # install activate complains if you haven't saved before an activation
    print("Saved!")

    print("\nExpanding .bin to .pkg files (step 1 of 3, takes a few minutes)...")
    command = "install add file flash:" + filename
    output = nr.run(netmiko_send_command, command_string=command, read_timeout=600)
    swan_logger.commandLogger(command, output)
 
    print("\nChanging .conf files (step 2 of 3, takes a few minutes)...")
    command2 = "install activate"
    output2 = nr.run(netmiko_send_command, command_string=command2, strip_command=False, read_timeout=600, expect_string=r"want to proceed", cmd_verify=False)
    swan_logger.commandLogger(command2, output2, "STARTCOMMAND")

    print("\nActivating new package (step 3 of 3, takes a few minutes)...")
    output3 = nr.run(netmiko_send_command, command_string="y", strip_command=False, read_timeout=600, expect_string=r"will reload the system", cmd_verify=False)
    swan_logger.commandLogger("y", output3, "ENDCOMMAND")

    print("\nRestarting...\n")



# CHECK ALIVE REBOOT2
# Completely different check alive function as NAPALM checks to see if port 22 is
# open in its is_alive() function, and port 22 never gets closed during the upgrade.
# Netmiko seems to encounter some socket closed error if you keep on running it's tasks on
# the same global nornir object (the nr one) during the upgrade process so that was also dropped.
# To fix these issues, I first reinitalize a completely new Nornir object in main()
# with all of the same configs and filtering as the global Nornir object and runs a NAPALM task
# over and over again until that task does not fail on any hosts, meaning that all hosts are
# online. This used to recreate a new host every query, but this was filling up switch TTY's
# Function returns 0 once all hosts come back online
################################################################################
def checkAliveReboot2(nr):
    hostnameList = list(nr.inventory.hosts.keys())      # List of all hostnames pulled from hosts.yaml inventory file
    now = datetime.now()
    print("Sleeping 5 minutes before starting to check if machines are up...")
    print(f"Current Time: ", now.strftime("%H:%M:%S"))
    time.sleep(300)
    print("5 minutes have elapsed\n")
    
    try:
        while True:
            print("\nPolling devices...")
            output = nr.run(napalm_get, getters="facts", on_failed=True)

            if len(nr.data.failed_hosts) == 0:
                print("All switches online")
                return 0
            elif len(nr.data.failed_hosts) > 0:
                for hostname in hostnameList:
                    if hostname in nr.data.failed_hosts:
                        print(f"{RED}{hostname}{CLEAR} is offline")
                    else:
                        print(f"{GREEN}{hostname}{CLEAR} is online")
            
            nr.data.reset_failed_hosts()                # Reseting failed host list so every host gets checked again next loop
            time.sleep(30)
    except KeyboardInterrupt:
        print("Exiting check alive loop")
        return 0




# UPGRADE FINISHER
# Runs the last couple of commands required to either commit or abort the upgrade
# Committing the upgrade takes a few seconds, while aborting the upgrade
# will cause the switches to reboot while rolling back changes
################################################################################
def upgradeFinisher(nr, answer):
    tempTime = datetime.now().strftime("%I:%M:%S %p")   # Listing out when the upgrade finished
    print(f"Upgrade Finished - {tempTime}")

    if "commit" in answer.lower():                      # If you want to commit the new upgrade
        print("\nCommitting IOS upgrade...")
        command = "install commit"
        output = nr.run(netmiko_send_command, command_string=command, read_timeout=600, expect_string=r"SUCCESS", cmd_verify=False)
        print("Successfully committed IOS upgrade!")
        swan_logger.commandLogger(command, output)
    
    elif "abort" in answer.lower():                     # If you want to abort the new upgrade
        print("\nAborting IOS upgrade...")
        command = "install abort"
        output = nr.run(netmiko_send_command, command_string=command, read_timeout=600, expect_string=r"want to proceed", cmd_verify=False)
        swan_logger.commandLogger(command, output, "STARTCOMMAND")
        
        print("\nRolling back changes...")
        output2 = nr.run(netmiko_send_command, command_string="y", read_timeout=600, expect_string=r"will reload the system", cmd_verify=False)
        print("\nRestarting...")
        swan_logger.commandLogger(command, output2, "ENDCOMMAND")



# UPGRADE CHECKER
# Function is ran after the upgrade has been committed, and checks to see if the
# switches' IOS version they have matches the IOS version you wanted to upgrade to.
# Function returns 0 if all switches match the new version and 1 if any switches
# do not match the new IOS version that was specified
################################################################################
def upgradeChecker(updatedSwitches, newIOSVer):
    mismatchVer = False
    
    for switch in updatedSwitches:
        if switch[1] != newIOSVer:                      # Checking to see if updated switch's version matches the new one provided in ios_file_data.py
            mismatchVer = True
            print(f"{RED}{switch[0]}{CLEAR}'s IOS version does not match the upgrade's IOS version")
            print(f"Switch Ver: {switch[1]}   Upgrade Ver: {newIOSVer}\n")
    
    if mismatchVer:
        print("One or more of the switches in the host list did not upgrade properly and does not match the new version")
        return 1
    else:
        print(f"{GREEN}All switches in the host list upgraded their IOS version to {newIOSVer}{CLEAR}")
        return 0



# REMOVE INACTIVE
# Function is ran as the very last thing before the script ends, asks user if
# they want to remove old IOS files to clear up some space
################################################################################
def removeInactive(nr):
    print("\nRemoving inactive files... (This may take a few minutes)")
    command = "install remove inactive"
    output = nr.run(netmiko_send_command, command_string=command, read_timeout=300, expect_string=r"Do you want to remove the above files", cmd_verify=False)   # 5 min wait
    swan_logger.commandLogger(command, output, "STARTCOMMAND")

    output2 = nr.run(netmiko_send_command, command_string="y", read_timeout=300, expect_string=r"SUCCESS: install_remove", cmd_verify=False)
    swan_logger.commandLogger(command, output2, "ENDCOMMAND")
    print("Inactive files removed!\n")

    print("Saving config...")
    nr.run(netmiko_save_config)                                     # Saving config before ending
    print("Config saved!")
    print("It may take a few minutes for the script to close all VTY sessions")
    swan_logger.commandLogger(command, output, "ENDLOG")            # Outputting ending banner in logs



# MAIN
################################################################################
def main():
    ################################################################################
    #                               PRECONFIGURATION                               #
    ################################################################################
    newIOSVersion, newFileServerIP, newFileServerPath, newIOSFile, newIOSMD5, newIOSSize = newIOSData() #Function populating new IOS file info
    
    configFile = "config.yaml"                          # String location of config.yaml file, passed to nornirInit to (re)create the nr object a few times
    nr = nornirInit(configFile)                         # Custom built initialization function that fixes bugs, look at checkAliveReboot2() for more details
    
    ################################################################################
    #                              9000 CONFIGURATION                              #
    ################################################################################  
    if checkAlive(nr) == 1:                             # Function only returns 1 if one or more switches are offline
        print(f"List of all hosts offline: {nr.data.failed_hosts}")
        print("\nExiting...")
        print("\nIf this failed on the first host in the inventory or you believe that")
        print("the host is alive, you may have mistyped your password")
        return

    filterFlag = bundleOrInstall(nr)                    # Determining what boot mode the switches are using
    if filterFlag == 1:                                 # Functions only returns 1 if one or more switches are in BUNDLE mode
        print("One or more switches in the host file are configured in BUNDLE mode,")
        print("this script only works on switches that are configured in INSTALL mode.")
        print("Please remove the offending switch from the \"install\" group in the")
        print("hosts.yaml file and run this script again.")
        return

    setIgnoreStartupCfg(nr)                             # Function sets register that may break upgrade
    checkAutoUpgrade(nr)                                # Function checks to see if switch is properly configured to update to all switches in stack
    resetBootVar(nr)                                    # See function for more details, but potentially needed function for IOS 17+

    switches = []                                       # Array that holds all switch data, current structure is hostname, IOS version, freespace in bytes:
                                                        # [['hostname','XX.XX.XX', 8000000000], ['hostname2','XX.XX.YY', 7000000000]]
    print("\nGathering switch data...")
    print("################################################################################\n")
    switchHostnames, temp = getSwitchData(nr)           # Using a whole bunch of getter methods to gather switch data, returns two arrays
    switchIOSVersion = []
    for version in temp:                                # Formatting the IOS versions once more, can never be too sure...
        switchIOSVersion.append(versionFormatter(version))
    switchFreeSpace = getFreeSpace(nr)

    print("Formatting data...\n")                       # Formatting all of the data into the switches array that was explained above
    for x in range(len(switchHostnames)):               # Using switchHostnames array length, but any of them should work as they should
        tempList = []                                   # all be the same size and in the same order as the hosts.yaml file
        tempList.append(switchHostnames[x])
        tempList.append(switchIOSVersion[x])
        tempList.append(switchFreeSpace[x])
        switches.append(tempList)

    printFormatter(switches, newIOSVersion)             # Prints out switch data formatted in table
    
    if len(switches) == 1:
        print(f"{len(switches)} switch in list\n")
    else:
        print(f"{len(switches)} switches in list\n")

    missingFile = missingFileChecker(nr, newIOSFile)    # Grabbing a list of switch hostnames that are missing the file
    if len(missingFile) == 0:                           # If all switches happen to have the .bin file
        print("All switches have the new file in their flash\n")
        if MD5Checker(nr, newIOSFile, newIOSSize, newIOSMD5) == 1:  # Function only returns 1 if hashes dont match, tells you in func which switch has the bad file
                print("Exiting...")
                return
    else:                                               # If one or more switches are missing the file
        while True:                                     # Loop for downloading the specified file
            print(f"One or more switches is missing {newIOSFile}")
            
            if checkFreeSpace(switches, newIOSSize, missingFile) == 1:  # Function only returns 1 if one or more switches dont have enough free space
                print("Exiting...")
                return

            scpEstimate(newIOSFile, newIOSSize)         # Estimates download speed
            answer = input("\nKnowing this, do you wish to start the transfer (yes or no)?\n")
            
            if "yes" in answer.lower():
                print("\n\nDownloading IOS files...")
                print("################################################################################")
                scpIOSBin(nr, newFileServerIP, newFileServerPath, newIOSFile, newIOSSize, missingFile)    # Downloads file only on switches that are missing the file
                print("Ensuring file was downloaded properly...\n")
                missingFileChecker(nr, newIOSFile)                          # Checking to make sure file now exists
                if MD5Checker(nr, newIOSFile, newIOSSize, newIOSMD5) == 1:  # Function only returns 1 if hashes dont match, tells you in func which switch has the bad file
                    print("Exiting...")
                    return
                break
            elif "no" in answer.lower():
                return
            else:
                print("Please either answer \"yes\" or \"no\".\n\n")

    skipFlag = True                                     # Flag for checking if checkAliveReboot2() is needed or not
    while True:                                         # Loop for upgrading new IOS version
        print("\n\nUpgrading the switches...")
        print("################################################################################\n")
        print(f"{newIOSFile} has been successfully downloaded on all switches")
        print("\nDo you wish to start the IOS upgrade process, skip this step, or stop the script (start/skip/stop)?")
        print("Skipping this step brings you to the option to commit, abort, or manually configure the upgrade")
        answer = input("NOTE: This will reboot the switches if you choose to start the upgrade\n")
        
        if "start" in answer.lower():
            upgradeIOS(nr, newIOSFile)
            break
        elif "stop" in answer.lower():
            return
        elif "skip" in answer.lower():
            print("\nSkipping step...")
            skipFlag = False
            break
        else:
            print("\n\nPlease either answer (start/stop/skip).")
    
    nornirLogger = logging.getLogger("nornir.core.task")
    nornirLogger.disabled = True                        # Temporarily disabling nornir.log error tracebacks as checkAliveReboot2() just spams the log full of 'em

    user, passw = credentialGrabber(nr)                 # User & Pass to automatically make downloadNR object
    pollingNR = nornirInit(configFile, user, passw)     # Nornir object used ONLY for figuring out when switch restarts
    while True and skipFlag:                            # Will only skip this step if skipFlag is set to false above
        if checkAliveReboot2(pollingNR) == 0:           # Function only returns a 0 once all switches are back online and can have a command ran on them
            break
    nornirLogger.disabled = False
    
    username, password = credentialGrabber(nr)          # Grabbing credentials to...
    nr2 = nornirInit(configFile, username, password)    # ...reinitialize the nornir object as the old one has timed out after reboot and will no longer run any commands,
                                                        # as it literally cant find the host. All future nornir calls use this nr2 object
    while True:
        print("\n\nFinalizing upgrade process...")
        print("################################################################################\n")
        print(f"IOS {newIOSVersion} has been installed on all switches")
        print("\nDo you wish to wish to commit, abort, manually configure the install, or skip (commit/abort/manual/skip)?")
        print("Skipping this step brings you to the option to remove inactive files [install remove inactive]")
        answer = input("NOTE: This will reboot the switches if you choose to abort the upgrade\n")

        if "commit" in answer.lower():
            upgradeFinisher(nr2, answer)
            break
        elif "abort" in answer.lower():
            upgradeFinisher(nr2, answer)
            break
        elif "manual" in answer.lower():
            tempTime = datetime.now().strftime("%I:%M:%S %p")   # Listing out when script ended
            print(f"Exiting script... - {tempTime}")
            return
        elif "skip" in answer.lower():
            print("\nSkipping step...")
            break
        else:
            print("Please either answer (commit/abort/manual/skip).\n\n")
    
    ################################################################################
    #                              POST-UPDATE CHECKS                              #
    ################################################################################ 
    updatedSwitches = []                                # Array that holds all switch data after the update has occured
    print("\n\nGathering upgraded switch data...")
    print("################################################################################\n")
    updatedSwitchHostnames, temp2 = getSwitchData(nr2)  # This is identical to the first time switch data was grabbed, so I'll spare you the comments
    updatedSwitchIOSVersion = []
    for version2 in temp2:
        updatedSwitchIOSVersion.append(versionFormatter(version2))
    updatedSwitchFreeSpace = getFreeSpace(nr2)

    print("Formatting data...\n")
    for x in range(len(updatedSwitchHostnames)):
        tempList2 = []
        tempList2.append(updatedSwitchHostnames[x])
        tempList2.append(updatedSwitchIOSVersion[x])
        tempList2.append(updatedSwitchFreeSpace[x])
        updatedSwitches.append(tempList2)

    printFormatter(updatedSwitches, newIOSVersion)      # Printing out table with new switch data
    print(f"{len(updatedSwitches)} Switches in list\n")
    print()
    upgradeChecker(updatedSwitches, newIOSVersion)      # Checking to ensure all switches match the new IOS version

    while True:                                         # Loop for asking if you want to remove inactive file
        answer = input("\nDo you want to remove inactive files [install remove inactive] (yes or no)?\n")
        
        if "yes" in answer.lower():
            removeInactive(nr2)
            break
        elif "no" in answer.lower():
            print("Saving config...")
            nr2.run(netmiko_save_config)                # Saving config before ending
            print("Config saved!")
            print("It may take a few minutes for the script to close all VTY sessions")
            swan_logger.commandLogger("", nr2.inventory.hosts.keys(), "ENDLOG") # Passing only the hostnames for the endlog
            return
        else:
            print("Please either answer \"yes\" or \"no\".\n\n")



if __name__ == "__main__":                              # Running main()
    main()