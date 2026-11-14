# CISA AA22-320A — Iranian Government-Sponsored APT Actors Compromise Federal Network

> Real public threat-intelligence report used as a demo input for CyberRange.
> This file is assembled from **verbatim excerpts** of the source advisory, kept in reading order,
> with each excerpt tagged by its source segment id (used as the citation locator).
>
> - Source: CISA Joint Cybersecurity Advisory AA22-320A
> - URL: https://www.cisa.gov/sites/default/files/publications/aa22-320a_joint_csa_iranian_government-sponsored_apt_actors_compromise_federal%20network_deploy_crypto%20miner_credential_harvester.pdf
> - Source SHA-256: `beacab7d0ed36ddc4e51b3e7a00e24ac9c612bfb29dffde3ffef01597b4109e2`
> - License: U.S. CISA advisory (public domain U.S. Government work).
> - Excerpts only; see the source PDF for the complete report.

**Incident:** Suspected Iranian government-sponsored compromise of an FCEB network through an unpatched VMware Horizon server

**Summary (reconstructed from the advisory):** Likely Iranian government-sponsored actors exploited Log4Shell on an unpatched VMware Horizon server, installed XMRig, moved through a VDI-KMS host to multiple systems and the domain controller, harvested credentials, created a rogue domain administrator account, deployed Ngrok reverse proxies, changed local administrator passwords, and unsuccessfully attempted to dump LSASS.

- Reported timeframe: February 2022
- Reported timeframe: April 2022
- Reported timeframe: mid-June through mid-July 2022

## Observed activity (verbatim excerpts, in order)

### Segment p0002

In February 2022, the threat actors exploited Log4Shell [T1190] for initial access [TA0001] to the organization’s unpatched VMware Horizon server.

As part of their initial exploitation, CISA observed a connection to known malicious IP address 182.54.217[.]2 lasting 17.6 seconds.

The actors’ exploit payload ran the following PowerShell command [T1059.001] that added an exclusion tool to Windows Defender [T1562.001]

Specifically, CISA observed HTTPS activity from IP address 51.89.181[.]64 to the organization’s VMware server.

Following HTTPS activity, CISA observed a suspected LDAP callback on port 443 to this IP address.

CISA also observed a DNS query for us‐nation‐ny[.]cf that resolved back to 51.89.181[.]64 when the victim server was returning this Log4Shell LDAP callback to the actors’ server.

CISA assessed that  this traffic indicated a confirmed compromise based on the successful callback to the indicator

### Segment p0003

By exploiting Log4Shell, the actors gained access to a VMware service account with administrator and system level access.

The exclusion tool allowlisted the entire c:\drive, enabling threat actors to download tools to the c:\drive without virus scans.

The exploit payload then downloaded mdeploy.text from 182.54.217[.]2/mdepoy.txt to C:\users\public\mde.ps1 [T1105].

When executed, mde.ps1 downloaded file.zip from 182.54.217[.]2 and removed mde.ps1 from the disk [T1070.004].

file.zip contained XMRig cryptocurrency mining software and associated configuration files.

After obtaining initial access and installing XMRig on the VMWare Horizon server

The exploit payload created a Scheduled Task [T1053.005] that executed RuntimeBroker.exe daily as SYSTEM.

The Scheduled Task was named RuntimeBrokerService.exe to masquerade as a legitimate Windows task.

the actors used RDP [T1021.001] and the built-in Windows user account DefaultAccount [T1078.001] to move laterally [TA0008] to a VMware VDI-KMS host.

Once the threat actor established themselves on the VDI-KMS host, CISA observed the actors download around 30 megabytes of files from transfer[.]sh server associated with 144.76.136[.]153.

The actors downloaded the following tools: 
• PsExec – a Microsoft signed tool for system administrators. 
• Mimikatz – a credential theft tool. 
• Ngrok – a reverse proxy tool

The threat actors then executed Mimikatz on VDI-KMS to harvest credentials

The threat actors then executed Mimikatz on VDI-KMS to harvest credentials and created a rogue domain administrator account [T1136.002].

Using the newly created account, the actors leveraged RDP to propagate to several hosts within the network.

Upon logging into each host, the actors manually disabled Windows Defender via the Graphical User Interface (GUI)

Upon logging into each host, the actors manually disabled Windows Defender via the Graphical User Interface (GUI) and implanted Ngrok executables and configuration files.

The threat actors were able to implant Ngrok on multiple hosts to ensure Ngrok’s persistence should they lose access to a machine during a routine reboot.

The actors were able to proxy [T1090] RDP sessions, which were only observable on the local network as outgoing HTTPS port 443 connections to tunnel.us.ngrok[.]com and korgn.su.lennut[.]com

### Segment p0009

The actors used Mimikatz to harvest credentials.

### Segment p0004

Once the threat actors established a deep foothold in the network and moved laterally to the domain controller

they executed the following PowerShell command on the Active Directory to obtain a list of all machines attached to the domain [T1018]

The threat actors also changed the password for the local administrator account [T1098] on several hosts as a backup should the rogue domain administrator account get detected and terminated.

the threat actor was observed attempting to dump the Local Security Authority Subsystem Service (LSASS) process [T1003.001] with task manager but this was stopped by additional anti-virus the FCEB organization had installed.

## Scope limitations (from the advisory)

- The organization was determined to have been compromised as early as February 2022, but the report does not provide exact timestamps for most attacker actions.
- The report describes several affected hosts collectively and does not provide their individual identities.
- A custom Ngrok domain and additional tunnel domains were possible but were explicitly not observed and are excluded from the actions.

