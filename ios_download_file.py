# Script by: DarkSplash
# Last edited: 02/27/2023

# This script is designed ONLY to download a file on an IOS or IOS-XE switch,
# although it may work on other models. Almost all of the functions used in this
# script are pullled from the INSTALL script. Currently the script looks for a
# file located somewhere in a specified fileserver directory and downloads it 
# while providing you with a download percent every 10 seconds. Additionially,
# it also ignores the IOSVersion variable in ios_file_data.py.

from datetime import datetime
import getpass
import ios_upgrade_INSTALL                              # Copying most functions from INSTALL script, BUNDLE will break on gathering switch data thanks to other variables not in this script
import ios_file_data
import logging
from nornir import InitNornir
from nornir.core.filter import F
from nornir_netmiko.tasks import netmiko_send_command
from nornir_netmiko.tasks import netmiko_save_config
import swan_logger                                      # Custom written logger script, look at commandLogger() or script for more details
import threading                                        # Searches for # of switches in a stack, which uses slightly differnt variables and printFormatter()
import os, signal, sys


# Packageless Terminal Colors: https://stackoverflow.com/a/21786287
RED = "\x1b[1;31;40m"
GREEN = "\x1b[1;32;40m"
CLEAR = "\x1b[0m"
FLAG = False                                            # Flag to determine when download has started in downloadPercentage() thread



# Function ignores IOS Version variable but is otherwise the same as install function
def newIOSData():
    while True:
        newFileServerIP = ios_file_data.FileServerIP
        newFileServerPath = ios_file_data.FileServerPath
        newIOSFile = ios_file_data.IOSFile
        newIOSMD5 = ios_file_data.IOSMD5
        newIOSSize = ios_file_data.IOSSize

        
        if newFileServerPath[0] == "/":
            print(f"\nFileserver path {RED}{newFileServerPath}{CLEAR} starts with a forward slash")
            print("Remove the forward slash from FileServerPath in ios_file_data.py and run this script again.\n")
            raise SystemExit(0)                         # Exiting script on incorrectly formatted download server path
        elif newFileServerPath[-1] == "/":
            print(f"\nFileserver path {RED}{newFileServerPath}{CLEAR} ends with a forward slash")
            print("Remove the forward slash from FileServerPath in ios_file_data.py and run this script again.\n")
            raise SystemExit(0)                         # Exiting script on incorrectly formatted download server path

        print(f"\nNew Fileserver IP: {newFileServerIP}")
        print(f"New Fileserver Path: {newFileServerPath}")
        print(f"New IOS File: {newIOSFile}")
        print(f"New IOS MD5: {newIOSMD5}")
        print(f"New IOS Size: {newIOSSize}")

        while True:
            answer = input("\n\nDo these values look correct (yes or no)?\n")
            if "yes" in answer.lower():
                print()
                return newFileServerIP, newFileServerPath, newIOSFile, newIOSMD5, newIOSSize
            elif "no" in answer.lower():
                print("\nVariable data is changed in ios_file_data.py")
                raise SystemExit(0)                     # Exiting script on incorrect data
            else:
                print("Please either answer \"yes\" or \"no\".\n")



# Grabbed because it is required in nornirInit()
def nornir_set_creds(nr, username=None, password=None):
    if not username:
        username = input("Enter username: ")
    if not password:
        password = getpass.getpass()

    for host_obj in nr.inventory.hosts.values():
        host_obj.username = username
        host_obj.password = password


# Grabbed because it is required in downloadPercentage()
def credentialGrabber(nr):
    username = ""                                       # Grabbing username and password so every recreation of the
    password = ""                                       # Nornir object doesn't prompt you for credentials
    for host in nr.inventory.hosts.values():
            username = host.username
            password = host.password
            break
    return username, password


# Removed INSTALL/BUNDLE filter so this works on all switches
def nornirInit(configFile, username=None, password=None):
    nr = InitNornir(config_file=configFile)             # Initializing Nornir object
    
    if username is not None and password is not None:   # Portion of code for re-initializing nornir object, look at checkAliveReboot2() for more info
        nornir_set_creds(nr, username, password)
    else:
        nornir_set_creds(nr)
    
    print()
    return nr



def killScript(nr, nr2, thread):
    nr.close_connections()                                  # Closing both nornir objects
    nr2.close_connections()
    thread.set()                                            # Stopping download thread

    if sys.platform == 'win32':
        os.kill(os.getpid(), signal.SIGBREAK)               # Literally the only method I found to have the script exit
    else:
        os.kill(os.getpid(), signal.SIGKILL)                # If you're not on windows


# Pretty much pilfered entirely from: https://stackoverflow.com/a/2223182
def downloadPercentage(nr, filename, filesize, thread, configFile, nr2):
    command = f"dir | i {filename}"

    try:
        output = nr.run(netmiko_send_command, command_string=command, read_timeout=15)
        for hostname in output:
            result = output[hostname].result
            if result == "" and FLAG:                       # FLAG will only be set to true if download process has started 
                print(f"\n{RED}File not found/download did not start, you likely mistyped your username or password{CLEAR}")
                print("Exiting script")
                killScript(nr, nr2, thread)
            
            temp = output[hostname].result.split()          # Third element (index 2) contains bytes downloaded
            percent = round(100*(int(temp[2])/filesize), 1) # Taking the current bytes downloaded and finding what percent the download is at
            
            if percent == 100.0:
                print(f"{GREEN}{hostname}{CLEAR} - {percent}% downloaded")
            else:
                print(f"{hostname} - {percent}% downloaded")
        print()
    except IndexError:                                      # Catching inital index error that is thrown once
        pass

    if not thread.is_set():                                 # If the thread hasnt been started, start every 10 seconds
        threading.Timer(10, downloadPercentage, [nr, filename, filesize, thread, configFile, nr2]).start()



# READ TIMEOUT ESTIMATE
# Function returns an int that represents how many seconds netmiko will wait
# to see a certain string.  This function assumes an abysmal speed of 
# 250 kibibytes/sec, and even adds another 1.5 hours for abysmal download speeds.
def readTimeoutEstimate(filesize):
    timeout = int(filesize/256000)                      # Calculating how many seconds download will take
    timeout = timeout + 5400                            # Adding 1.5 hours so timing out shouldn't happen due to slow downloads
    return timeout



# SCP IOS BIN
# Custom SCP IOS BIN function with super long timeout for downloads
################################################################################
def scpIOSBin(nr, ipAddress, folderPath, filename, filesize, missingFile):
    global FLAG

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
    FLAG = True
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



# MAIN - Copied from INSTALL, but all INSTALL only functions have been removed
################################################################################
def main():
    ################################################################################
    #                               PRECONFIGURATION                               #
    ################################################################################
    newFileServerIP, newFileServerPath, newIOSFile, newIOSMD5, newIOSSize = newIOSData() #Function populating new IOS file info
    
    configFile = "config.yaml"                          # String location of config.yaml file, passed to nornirInit to (re)create the nr object a few times
    nr = nornirInit(configFile)                         # Slightly modified nornirInit, does not filter by INSTALL or BUNDLE
    swan_logger.commandLogger("", nr.inventory.hosts.keys(), "STARTLOG")
    ################################################################################
    #                              9000 CONFIGURATION                              #
    ################################################################################  
    if ios_upgrade_INSTALL.checkAlive(nr) == 1:         # Function only returns 1 if one or more switches are offline
        print(f"List of all hosts offline: {nr.data.failed_hosts}")
        print("\nExiting...")
        print("\nIf this failed on the first host in the inventory or you believe that")
        print("the host is alive, you may have mistyped your password")
        return

    switches = []                                       # Array that holds all switch data, current structure is hostname, IOS version, freespace in bytes:
                                                        # [['hostname','XX.XX.XX', 8000000000], ['hostname2','XX.XX.YY', 7000000000]]
    print("\nGathering switch data...")
    print("################################################################################\n")
    switchHostnames, temp = ios_upgrade_INSTALL.getSwitchData(nr)   # Using a whole bunch of getter methods to gather switch data, returns two arrays
    switchIOSVersion = []
    for version in temp:                                # Formatting the IOS versions once more, can never be too sure...
        switchIOSVersion.append(ios_upgrade_INSTALL.versionFormatter(version))
    switchFreeSpace = ios_upgrade_INSTALL.getFreeSpace(nr)

    print("Formatting data...\n")                       # Formatting all of the data into the switches array that was explained above
    for x in range(len(switchHostnames)):               # Using switchHostnames array length, but any of them should work as they should
        tempList = []                                   # all be the same size and in the same order as the hosts.yaml file
        tempList.append(switchHostnames[x])
        tempList.append(switchIOSVersion[x])
        tempList.append(switchFreeSpace[x])
        switches.append(tempList)

    ios_upgrade_INSTALL.printFormatter(switches, "xx.xx.xx")             # Prints out switch data formatted in table
    print(f"{len(switches)} Switches in list\n")

    missingFile = ios_upgrade_INSTALL.missingFileChecker(nr, newIOSFile)    # Grabbing a list of switch hostnames that are missing the file
    if len(missingFile) == 0:                           # If all switches happen to have the specified file
        print("All switches have the new file in their flash\n")
        if ios_upgrade_INSTALL.MD5Checker(nr, newIOSFile, newIOSSize, newIOSMD5) == 1:  # Function only returns 1 if hashes dont match, tells you in func which switch has the bad file
                print("Exiting...")
                return
    else:                                               # If one or more switches are missing the file
        while True:                                     # Loop for downloading the specified file
            print(f"One or more switches is missing {newIOSFile}")
            
            if ios_upgrade_INSTALL.checkFreeSpace(switches, newIOSSize, missingFile) == 1:  # Function only returns 1 if one or more switches dont have enough free space
                print("Exiting...")
                return
            
            ios_upgrade_INSTALL.scpEstimate(newIOSFile, newIOSSize)     # Estimates download speed
            answer = input("\nKnowing this, do you wish to start the transfer (yes or no)?\n")
            
            if "yes" in answer.lower():
                print("\n\nDownloading file...")
                print("################################################################################")
                
                username, password = credentialGrabber(nr)              # User & Pass to automatically make downloadNR object
                dlNR = nornirInit(configFile, username, password)       # Nornir object used ONLY for figuring out download percentage
                downloadNR = dlNR.filter(F(name__in=missingFile))       # Filtering to only switches that need downloads
                
                downloadThread = threading.Event()      # Starting download thread
                downloadPercentage(downloadNR, newIOSFile, newIOSSize, downloadThread, configFile, nr)
                
                scpIOSBin(nr, newFileServerIP, newFileServerPath, newIOSFile, newIOSSize, missingFile)  # Downloads file only on switches that are missing the file
                downloadThread.set()                    # Stopping download thread
                tempTime = datetime.now().strftime("%I:%M:%S %p")
                print(f"Finished Download: {tempTime}")

                print("Ensuring file was downloaded properly...\n")
                ios_upgrade_INSTALL.missingFileChecker(nr, newIOSFile)                          # Checking to make sure file now exists
                if ios_upgrade_INSTALL.MD5Checker(nr, newIOSFile, newIOSSize, newIOSMD5) == 1:  # Function only returns 1 if hashes dont match, tells you in func which switch has the bad file
                    print("Exiting...")
                    return
                break
            elif "no" in answer.lower():
                return
            else:
                print("Please either answer \"yes\" or \"no\".\n\n")
    
    print("\nSaving config...")
    nr.run(netmiko_save_config)                         # Saving config before ending
    print("Config saved!\n")
    print("It may take 1-2 minutes for the script to close all connections")
    print("if this script is being ran against a large number of hosts.")
    print("Do not try to Ctrl+C out, the script will just ignore the interrupt")

    swan_logger.commandLogger("", nr.inventory.hosts.keys(), "ENDLOG")
    nr.close_connections()
    dlNR.close_connections()                            # Unsure if this will speed up the script exit, not able to test with a large number of switches



if __name__ == "__main__":                              # Running main()
    main()