# Script by: DarkSplash
# Last edited: 02/27/2023

from datetime import date
from nornir.core.task import AggregatedResult
import os


# COMMAND LOGGER
# Custom written log thats purpose is to output the actual IOS commands and
# outputs from a run(netmiko_send_command) call to a file for ease of debugging. 
# Logs are output to a /logs directory that is made in the same directory as the script.
# This function SHOULD be called within any Nornir script that needs logging.
################################################################################
def commandLogger(command, output, flag=None):
    """
    Function takes a Cisco command string and a Nornir AggregatedResult object
    that is returned after running a Nornir run(netmiko_send_command) function 
    and takes each host and logs the command and the command output to a log 
    file located in the /logs folder within the script directory.

    Parameters
    ----------
    command : string
        The IOS command that was ran, only matters during calls with no flag or
        during the "STARTCOMMAND" flag.
    output : AggregatedResult
        The Nornir output after a run() function call.
    flag : string, optional
        The optional flag that allows you to log command that have more than
        one batch of output. By default this is None, but during multi-output
        commands, the other flags are "STARTCOMMAND", "CONTINUECOMMAND", and
        "ENDCOMMAND".
    """
    if not isinstance(output, AggregatedResult):        # Special case for very last call for the ENDLOG banner at bottom of main()
        for hostname in output:                         # Doesnt like getting a .result from a non AggregatedResult variable
            logger(hostname, command, "", flag)
    else:
        for hostname in output:
            result = output[hostname].result
            logger(hostname, command, result, flag)     # Same as above, but splitting each log call by hostname so they each have their own log file


# LOGGER
# Logging function that takes each individual host and logs them to their
# respective file, or creates the file if it has not been created yet.
# This function SHOULD NOT be called in the actual script, as it was designed
# to be called within commandLogger().
def logger(switchHostname, command, result, flag=None):
    ################################################################################
    #                          LOGGING DIRECTORY CREATION                          #
    ################################################################################ 
    scriptDir = os.getcwd()                             # Gets current directory of where script is being ran
    loggingDir = scriptDir + "/logs/"                   # Logging subdirectory direct path
    currentDate = date.today().strftime("%Y-%m-%d")
    filename = f"{currentDate}-{switchHostname}.log"    # Filename is current day + switch hostname
    
    if not os.path.exists(loggingDir):                  # Creates logging directory if it doesnt exist
        print("Logging directory doesn't exist, creating...")
        os.mkdir(loggingDir)
    
    ################################################################################
    #                            SWITCH COMMAND LOGGING                            #
    ################################################################################ 
    filepath = loggingDir + filename                    # Full file path of log file
    with open(filepath, "a") as log:
        if flag is not None:                            # Checking to see if any special flags were passed
            if "STARTLOG" in flag:                      # Special script start banner
                log.write("########################################\n")
                log.write("#             START SCRIPT             #\n")
                log.write("########################################\n\n")
                return
            elif "STARTCOMMAND" in flag:                # Allows you to log Nornir commands that have more than one output variable, first flag to be called
                log.write(command + "\n")
                log.write("########################################\n")
                log.write(result)
                return
            elif "CONTINUECOMMAND" in flag:             # Allows you to log Nornir commands that have more than one output variable, second flag to be called
                log.write(command + "\n")               # (Only should be needed if 3 or more nornir output variables are used, like during a scp copy)
                log.write(result)
                return
            elif "ENDCOMMAND" in flag:                  # Allows you to log Nornir commands that have more than one output variable, last flag to be called
                log.write(command + "\n")
                log.write(result + "\n\n\n")
                return
            elif "ENDLOG" in flag:                      # Special script end banner
                log.write("########################################\n")
                log.write("#              END SCRIPT              #\n")
                log.write("########################################\n\n")
                return
        else:                                           # Default command logger
            log.write(command + "\n")
            log.write("########################################\n")
            log.write(result + "\n\n\n")