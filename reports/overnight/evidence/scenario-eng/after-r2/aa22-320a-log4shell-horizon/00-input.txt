# CISA AA22-320A — Iranian Government-Sponsored APT Actors Compromise Federal Network, Deploy Crypto Miner, Credential Harvester

> - Publisher: CISA and FBI, Joint Cybersecurity Advisory, Product ID AA22-320A, November 16, 2022 (TLP:CLEAR)
> - Web page: https://www.cisa.gov/news-events/cybersecurity-advisories/aa22-320a
> - PDF: https://www.cisa.gov/sites/default/files/publications/aa22-320a_joint_csa_iranian_government-sponsored_apt_actors_compromise_federal%20network_deploy_crypto%20miner_credential_harvester.pdf
> - PDF SHA-256: beacab7d0ed36ddc4e51b3e7a00e24ac9c612bfb29dffde3ffef01597b4109e2 (`source.pdf`, 14 pages)
> - License: U.S. Government work, TLP:CLEAR
> - Scope of this file: SUMMARY and TECHNICAL DETAILS (advisory pages 1–4), verbatim. The ATT&CK table, incident-response and mitigation sections are in `source.pdf.txt`.
> - Retrieved: 2026-11-15
> - Wording: the text below is the source's own wording; only page furniture, layout indentation and line wrapping were removed (see `reports/overnight/evidence/cti-research/build_reports.py`).

## SUMMARY

From mid-June through mid-July 2022, CISA conducted an incident response engagement at a Federal Civilian Executive Branch (FCEB) organization where CISA observed suspected advanced persistent threat (APT) activity. In the course of incident response activities, CISA determined that cyber threat actors exploited the Log4Shell vulnerability in an unpatched VMware Horizon server, installed XMRig crypto mining software, moved laterally to the domain controller (DC), compromised credentials, and then implanted Ngrok reverse proxies on several hosts to maintain persistence. CISA and the Federal Bureau of Investigation (FBI) assess that the FCEB network was compromised by Iranian government-sponsored APT actors. CISA and FBI are releasing this Cybersecurity Advisory (CSA) providing the suspected Iranian government-sponsored actors’ tactics, techniques, and procedures (TTPs) and indicators of compromise (IOCs) to help network defenders detect and protect against related compromises. CISA and FBI encourage all organizations with affected VMware systems that did not immediately apply available patches or workarounds to assume compromise and initiate threat hunting activities. If suspected initial access or compromise is detected based on IOCs or TTPs described in this CSA, CISA and FBI encourage organizations to assume lateral movement by threat actors, investigate connected systems (including the DC), and audit privileged accounts. All organizations, regardless of identified evidence of compromise, should apply the recommendations in the Mitigations section of this CSA to protect against similar malicious cyber activity. For more information on Iranian government-sponsored Iranian malicious cyber activity, see CISA’s Iran Cyber Threat Overview and Advisories webpage and FBI’s Iran Threats webpage. For a downloadable copy of IOCs, see: AA22-320A.stix, 155 mb.

## TECHNICAL DETAILS

Note: This advisory uses the MITRE ATT&CK for Enterprise framework, version 12. See the MITRE ATT&CK Tactics and Techniques section for a table of the threat actors’ activity mapped to MITRE ATT&CK® tactics and techniques with corresponding mitigation and/or detection recommendations.

### Overview

In April 2022, CISA conducted retrospective analysis using EINSTEIN—an FCEB-wide intrusion detection system (IDS) operated and monitored by CISA—and identified suspected APT activity on an FCEB organization’s network. CISA observed bi-directional traffic between the network and a known malicious IP address associated with exploitation of the Log4Shell vulnerability (CVE-2021- 44228) in VMware Horizon servers. In coordination with the FCEB organization, CISA initiated threat hunting incident response activities; however, prior to deploying an incident response team, CISA observed additional suspected APT activity. Specifically, CISA observed HTTPS activity from IP address 51.89.181[.]64 to the organization’s VMware server. Based on trusted third-party reporting, 51.89.181[.]64 is a Lightweight Directory Access Protocol (LDAP) server associated with threat actors exploiting Log4Shell. Following HTTPS activity, CISA observed a suspected LDAP callback on port 443 to this IP address. CISA also observed a DNS query for us‐nation‐ny[.]cf that resolved back to 51.89.181[.]64 when the victim server was returning this Log4Shell LDAP callback to the actors’ server. CISA assessed that this traffic indicated a confirmed compromise based on the successful callback to the indicator and informed the organization of these findings; the organization investigated the activity and found signs of compromise. As trusted-third party reporting associated Log4Shell activity from 51.89.181[.]64 with lateral movement and targeting of DCs, CISA suspected the threat actors had moved laterally and compromised the organization’s DC. From mid-June through mid-July 2022, CISA conducted an onsite incident response engagement and determined that the organization was compromised as early as February 2022, by likely Iranian government-sponsored APT actors who installed XMRig crypto mining software. The threat actors also moved laterally to the domain controller, compromised credentials, and implanted Ngrok reverse proxies.

### Threat Actor Activity

In February 2022, the threat actors exploited Log4Shell [T1190] for initial access [TA0001] to the organization’s unpatched VMware Horizon server. As part of their initial exploitation, CISA observed a connection to known malicious IP address 182.54.217[.]2 lasting 17.6 seconds. The actors’ exploit payload ran the following PowerShell command [T1059.001] that added an exclusion tool to Windows Defender [T1562.001]:

```
powershell try{Add-MpPreference -ExclusionPath 'C:\'; Write-Host 'added-
exclusion'} catch {Write-Host 'adding-exclusion-failed' }; powershell -enc
"$BASE64 encoded payload to download next stage and execute it"
```

The exclusion tool allowlisted the entire c:\drive, enabling threat actors to download tools to the c:\drive without virus scans. The exploit payload then downloaded mdeploy.text from 182.54.217[.]2/mdepoy.txt to C:\users\public\mde.ps1 [T1105]. When executed, mde.ps1 downloaded file.zip from 182.54.217[.]2 and removed mde.ps1 from the disk [T1070.004]. file.zip contained XMRig cryptocurrency mining software and associated configuration files.

- WinRing0x64.sys – XMRig Miner driver

- wuacltservice.exe – XMRig Miner

- config.json – XMRig miner configuration

- RuntimeBroker.exe – Associated file. This file can create a local user account [T1136.001] and tests for internet connectivity by pinging 8.8.8.8 [T1016.001]. The exploit payload created a Scheduled Task [T1053.005] that executed RuntimeBroker.exe daily as SYSTEM. Note: By exploiting Log4Shell, the actors gained access to a VMware service account with administrator and system level access. The Scheduled Task was named RuntimeBrokerService.exe to masquerade as a legitimate Windows task.

See MAR 10387061-1.v1 for additional information, including IOCs, on these four files.

After obtaining initial access and installing XMRig on the VMWare Horizon server, the actors used RDP [T1021.001] and the built-in Windows user account DefaultAccount [T1078.001] to move laterally [TA0008] to a VMware VDI-KMS host. Once the threat actor established themselves on the VDI-KMS host, CISA observed the actors download around 30 megabytes of files from transfer[.]sh server associated with 144.76.136[.]153. The actors downloaded the following tools:

- PsExec – a Microsoft signed tool for system administrators.

- Mimikatz – a credential theft tool.

- Ngrok – a reverse proxy tool for proxying an internal service out onto an Ngrok domain, which the user can then access at a randomly generated subdomain at *.ngrok[.]io. CISA has observed this tool in use by some commercial products for benign purposes; however, this process bypasses typical firewall controls and may be a potentially unwanted application in production environments. Ngrok is known to be used for malicious purposes.[1]

The threat actors then executed Mimikatz on VDI-KMS to harvest credentials and created a rogue domain administrator account [T1136.002]. Using the newly created account, the actors leveraged RDP to propagate to several hosts within the network. Upon logging into each host, the actors manually disabled Windows Defender via the Graphical User Interface (GUI) and implanted Ngrok executables and configuration files. The threat actors were able to implant Ngrok on multiple hosts to ensure Ngrok’s persistence should they lose access to a machine during a routine reboot. The actors were able to proxy [T1090] RDP sessions, which were only observable on the local network as outgoing HTTPS port 443 connections to tunnel.us.ngrok[.]com and korgn.su.lennut[.]com (the prior domain in reverse). It is possible, but was not observed, that the threat actors configured a custom domain, or used other Ngrok tunnel domains, wildcarded here as *.ngrok[.]com, *.ngrok[.]io, ngrok.*.tunnel[.]com, or korgn.*.lennut[.]com. Once the threat actors established a deep foothold in the network and moved laterally to the domain controller, they executed the following PowerShell command on the Active Directory to obtain a list of all machines attached to the domain [T1018]:

```
Powershell.exe get-adcomputer -filter * -properties * | select
name,operatingsystem,ipv4address &gt;
```

The threat actors also changed the password for the local administrator account [T1098] on several hosts as a backup should the rogue domain administrator account get detected and terminated. Additionally, the threat actor was observed attempting to dump the Local Security Authority Subsystem Service (LSASS) process [T1003.001] with task manager but this was stopped by additional anti-virus the FCEB organization had installed.
