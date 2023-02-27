# nornir-ios-code-upgrade
This repository contains a few python scripts that were developed with the purpose of batch upgrading the IOS or IOS-XE version on Cisco Catalyst 9000 series switches.

### Table of Contents
- [Overview](#overview)
- [Script Setup](#script-setup)
- [Script Execution](#script-execution)
- [Script Successes](#script-successes)
- [Script Caveats](#script-caveats)

## Overview
- [ios_upgrade_INSTALL.py](ios_upgrade_INSTALL.py) Script to upgrade switches whose switch image is using INSTALL mode
- [ios_upgrade_BUNDLE.py](ios_upgrade_BUNDLE.py) Script to upgrade switches whose switch image is using BUNDLE mode
    - Additionally, this script takes BUNDLE mode switches and converts them to INSTALL mode automatically as part of the upgrade process
- [ios_download_file.py](ios_download_file.py) Script to download a specified file via SCP

This script uses Nornir, NAPALM, and netmiko to do the following:
- Checks to make sure all switches in the hosts file are online and responding to the script
- Gathers data about all switches in the hosts file (Current IOS version, amount of free space, number of switches in a stack in the BUNDLE script, and if it already has the new IOS file downloaded)
- Downloads the new IOS file to all switches that are missing the file and verifies that the file was not corrupted (MD5 hash verification)
- Installs the new IOS version on all hosts
- Waits for the switches to come back online after rebooting during the upgrade process
    - If during the reboot process one switch is holding everything else back, you can press `Ctrl+C` **_ONCE_** to skip ahead as if all switches were online. Be careful to only press Ctrl+C once, as double pressing it will exit the script
- Allows the user to commit or abort the upgrade after all switches have come back online
    - This is not possible in the BUNDLE mode script as Cisco forces you to commit the upgrade all in one command
- Optionally allows the user to remove all old IOS files after the upgrade to free up space on all hosts
- Logs all Nornir and Cisco IOS commands in case something goes wrong
    - Nornir log stored in <ins>**nornir.log**</ins> located in the same directory as the script
    - Cisco IOS logs for each switch stored in a <ins>**/logs**</ins> directory that is made during script execution

Currently this script can only run on one IOS version/switch model at a time (I.E. Can run all 9300s at once or all 9200s at once but can't do 9300s and 9200s in the same run, the script would have to be ran twice due to different .bin files being used).

---

A secondary script has also been made named `ios_download_file.py` that's sole purpose is to download the specified file in `ios_file_data.py` to all other hosts in the inventory, regardless if the switch is INSTALL or BUNDLE mode.  You may have limited success using this script on non c9000 series switches (I've had it work on a c3650 and a c3560).

There is some additional functionality in `ios_download_file.py` compared to the INSTALL and BUNDLE scripts
- Reports what percentage your download is at for all switches every 10 seconds
- Ignores the <ins>**IOSVersion**</ins> variable in <ins>**ios_file_data.py**</ins> so you can download any file type without adding a fake version variable
- Does not run <ins>**software auto-upgrade enable**</ins>, <ins>**no system ignore startupconfig switch all**</ins>, and other pre-update configs that are in the INSTALL and BUNDLE scripts

While any of the scripts can download the file to the switches, I would recommend using `ios_download_file.py` to download files if you plan on updating a large number of switches, and after the download, run the respective upgrade scripts.

A third script named `swan_logger.py` is a logging script that takes in Nornir's unique datatype and parses it out into a unique log file for every switch and every day (I.E. if the script was ran on the same switch two days in a row, there would be two different logging files, one for each day).

## Script Setup
First, run `python3 -m pip install -r requirements.txt -U` to download all of the required python packages for the script.

Next, a `hosts.yaml` file needs to be created and populated with the list of switches that this script is running against.  Groups are required to be set within the host file, with each host being either in the <ins>**install**</ins> or <ins>**bundle**</ins> group depending on the switch's config (Look at the [hosts_example.yaml](examples/hosts_example.yaml) file inside the examples folder for more details).  You can determine what mode a switch is in by running `show version` and looking on the right side.

Finally, the variables in `ios_file_data.py` will need to be updated with the new file information.  Below is what an example would look like if you wanted to download the file <ins>**/srv/fileshare/cat9k_iosxe.16.09.01.SPA.bin**</ins> from <ins>**192.168.0.50**</ins> to the switches.
```
IOSVersion = "16.09.01"                       (XX.XX.XX)
FileServerIP = "192.168.0.50"                 (IP address of file server)
FileServerPath = "srv/fileshare"              (Path to file directory with no starting or ending forward slashes)
IOSFile = "cat9k_iosxe.16.09.01.SPA.bin"      (file to download in FileServerPath directory)
IOSMD5 = "258fb60ca843a2db78d8dba5a9f64180"   (MD5 hash of file to download)
IOSSize = 699968920                           (File size in bytes)
```

`md5sum {filename}` is an easy Linux command on how to get the MD5 value, while `ls -al` or `ll` should be two easy ways of checking for file size.

## Script Execution
As said earlier, technically you can just run either `ios_upgrade_INSTALL.py` or `ios_upgrade_BUNDLE.py` and the script will work just fine, but due to the amount of time it takes to download the files and the fact that `ios_download_file.py` has additional downloading functionality, I would highly recommend running `ios_download_file.py` first before continuing on and running the other two main scripts.

At runtime, the INSTALL and BUNDLE scripts will check to make sure your switch actually is that install mode, and then will proceed on through the upgrade process.

## Script Successes
These scripts successfully upgraded 470 c9300 switches all across Purdue University over 10 RFCs over a duration three weeks in the summer 2022.  These upgrades were typically in batches of around 50.  Took three hours to upgrade all switches and run an additional smart license script (that normally took one of those three hours).  This included numerous other statewide Purdue owned facilities that were not located on the Main Campus, alongside some old switches that were upgraded to boot in the newer and faster INSTALL mode instead of BUNDLE mode.

## Script Caveats
This was my first big Python script, so there was a lot I didn't know at the time, and are quite a few things I would do differently if I were to refactor/remake this script:

- First and foremost, break up the script into smaller more modular scripts
    - It's a giant pain doing the same edit three different times across ios_upgrade_INSTALL.py, ios_upgrade_BUNDLE.py, and ios_download_file.py
    - Scripts have also gotten so long that just finding functions can be annoying
    - Likely follow a similar structure to [another script of mine](https://github.com/DarkSplash/python-sharepoint-file-manager) (Main logic scripts and core reused scripts)
- Change my documentation style
    - Use NumPy style docstrings to document functions instead of whatever I was doing when I was writing this script
    - More clearly indicate where and why certain functions are used within the new docstrings [like this](https://github.com/DarkSplash/pingplotter-csv-graph/blob/main/graph.py#L110).
- Work still more on simplifying README and script instructions
    - For everyone but me, getting this jumbled mess of code working can be a bit of a doozie, so I would like to still improve upon my technical writing portion of this script
    - Perhaps make a video running through script setup to complement the README