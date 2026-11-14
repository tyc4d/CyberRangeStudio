# CISA AA23-158A — #StopRansomware: CL0P Ransomware Gang Exploits CVE-2023-34362 MOVEit Vulnerability

> - Publisher: FBI and CISA, Joint Cybersecurity Advisory, Product ID AA23_158A, June 7, 2023 (TLP:CLEAR)
> - Web page: https://www.cisa.gov/news-events/cybersecurity-advisories/aa23-158a
> - PDF: https://www.cisa.gov/sites/default/files/2023-06/aa23-158a-stopransomware-cl0p-ransomware-gang-exploits-moveit-vulnerability.pdf
> - PDF SHA-256: f9b23261a8c29328879fd37dcb8241aedfc2af13bc06042a0f90e927aeb7518e (`source.pdf`, 22 pages, as retrieved on the date below; CISA has revised this advisory since first publication)
> - License: U.S. Government work, TLP:CLEAR
> - Scope of this file: SUMMARY and TECHNICAL DETAILS (advisory pages 1–4), verbatim. The "Actions to take today" sidebar, YARA rules, IOC tables, ATT&CK tables and mitigations are in `source.pdf.txt`.
> - Retrieved: 2026-11-15
> - Wording: the text below is the source's own wording; only page furniture, layout indentation and line wrapping were removed (see `reports/overnight/evidence/cti-research/build_reports.py`).

## SUMMARY

Note: this joint Cybersecurity Advisory (CSA) is part of an ongoing #StopRansomware effort to publish advisories for network defenders that detail various ransomware variants and ransomware threat actors. These #StopRansomware advisories include recently and historically observed tactics, techniques, and procedures (TTPs) and indicators of compromise (IOCs) to help organizations protect against ransomware. Visit stopransomware.gov to see all #StopRansomware advisories and to learn more about other ransomware threats and no-cost resources.

The Federal Bureau of Investigation (FBI) and the Cybersecurity and Infrastructure Security Agency (CISA) are releasing this joint CSA to disseminate known CL0P ransomware IOCs and TTPs identified through FBI investigations as recently as June 2023.

According to open source information, beginning on May 27, 2023, CL0P Ransomware Gang, also known as TA505, began exploiting a previously unknown SQL injection vulnerability (CVE-2023-34362) in Progress Software's managed file transfer (MFT) solution known as MOVEit Transfer. Internet-facing MOVEit Transfer web applications were infected with a web shell named LEMURLOOT, which was then used to steal data from underlying MOVEit Transfer databases. In similar spates of activity, TA505 conducted zero-day-exploit-driven campaigns against Accellion File Transfer Appliance (FTA) devices in 2020 and 2021, and Fortra/Linoma GoAnywhere MFT servers in early 2023.

## TECHNICAL DETAILS

Note: This advisory uses the MITRE ATT&CK® for Enterprise framework, version 13. See MITRE ATT&CK for Enterprise for all referenced tactics and techniques.

Appearing in February 2019, and evolving from the CryptoMix ransomware variant, CL0P was leveraged as a Ransomware as a Service (RaaS) in large-scale spear-phishing campaigns that used a verified and digitally signed binary to bypass system defenses. CL0P was previously known for its use of the ‘double extortion’ tactic of stealing and encrypting victim data, refusing to restore victim access and publishing exfiltrated data on Tor via the CL0P^_-LEAKS website. In 2019, TA505 actors leveraged CL0P ransomware as the final payload of a phishing campaign involving a macro-enabled document that used a Get2 malware dropper for downloading SDBot and FlawedGrace. In recent campaigns beginning 2021, CL0P preferred to rely mostly on data exfiltration over encryption.

Beyond CL0P ransomware, TA505 is known for frequently changing malware and driving global trends in criminal malware distribution. Considered to be one of the largest phishing and malspam distributors worldwide, TA505 is estimated to have compromised more than 3,000 U.S.-based organizations and 8,000 global organizations.

TA505 has operated:

- A RaaS and has acted as an affiliate of other RaaS operations,

- As an initial access broker (IAB), selling access to compromised corporate networks,

- As a customer of other IABs,

- And as a large botnet operator specializing in financial fraud and phishing attacks.

In a campaign from 2020 to 2021, TA505 used several zero-day exploits to install a web shell named DEWMODE on internet-facing Accellion FTA servers. Similarly, the recent exploitation of MOVEit Transfer, a SQL injection vulnerability was used to install the web shell, which enabled TA505 to execute operating system commands on the infected server and steal data.

In late January 2023, the CL0P ransomware group launched a campaign using a zero-day vulnerability, now catalogued as CVE-2023-0669, to target the GoAnywhere MFT platform. The group claimed to have exfiltrated data from the GoAnywhere MFT platform that impacted approximately 130 victims over the course of 10 days. Lateral movement into the victim networks from the GoAnywhere MFT was not identified, suggesting the breach was limited to the GoAnywhere platform itself. Over the next several weeks, as the exfiltrated data was parsed by the group, ransom notes were sent to upper-level executives of the victim companies, likely identified through open source research. The ransom notes threatened to publish the stolen files on the CL0P data leak site if victims did not pay the ransom amount.

Figure 1: CL0P Ransom Note

```
Hello, this is the CL0P hacker group. As you may know, we recently carried
out a hack, which was reported in the news on site [redacted].
We want to inform you that we have stolen important information from your
GoAnywhere MFT resource and have attached a full list of files as evidence.
We deliberately did not disclose your organization and wanted to negotiate
with you and your leadership first. If you ignore us, we will sell your
information on the black market and publish it on our blog, which receives
30-50 thousand unique visitors per day. You can read about us on [redacted]
by searching for CLOP hacker group.
You can contact us using the following contact information:
unlock@rsv-box[.]com
and
unlock@support-mult[.]com
```

CL0P’s toolkit contains several malware types to collect information, including the following:

- FlawedAmmyy/FlawedGrace remote access trojan (RAT) collects information and attempts to communicate with the Command and Control (C2) server to enable the download of additional malware components [T1071], [T1105].

- SDBot RAT propagates the infection, exploiting vulnerabilities and dropping copies of itself in removable drives and network shares [T1105]. It is also capable of propagating when shared though peer-to-peer (P2P) networks. SDBot is used as a backdoor [T1059.001] to enable other commands and functions to be executed in the compromised computer. This malware uses application shimming for persistence and to avoid detection [T1546.011].

- Truebot is a first-stage downloader module that can collect system information and take screenshots [T1113], developed and attributed to the Silence hacking group. After connecting to the C2 infrastructure, Truebot can be instructed to load shell code [T1055] or DLLs [T1574.002], download additional modules [T1129], run them, or delete itself [T1070]. In the case of TA505, Truebot has been used to download FlawedGrace or Cobalt Strike beacons.

- Cobalt Strike is used to expand network access after gaining access to the Active Directory (AD) server [T1018].

- DEWMODE is a web shell written in PHP designed to target Accellion FTA devices and interact with the underlying MySQL database, and is used to steal data from the compromised device [1505.003].

- LEMURLOOT is a web shell written in C# designed to target the MOVEit Transfer platform. The web shell authenticates incoming http requests via a hard-coded password and can run commands that will download files from the MOVEit Transfer system, extract its Azure system settings, retrieve detailed record information, create, insert,, or delete a particular user. When responding to the request, the web shell returns data in a gzip compressed format.

### CVE-2023-34362 MOVEIT TRANSFER VULNERABILITY

MOVEit is typically used to manage an organization’s file transfer operations and has a web application that supports MySQL, Microsoft SQL Server, and Azure SQL database engines. In May 2023, the CL0P ransomware group exploited a SQL injection zero-day vulnerability CVE-2023-34362 to install a web shell named LEMURLOOT on MOVEit Transfer web applications [T1190] [1]. The web shell was initially observed with the name human2.aspx in an effort to masquerade as the legitimate human.aspx file present as part of MOVEit Transfer software. Upon installation, the web shell creates a random 36 character password to be used for authentication. The web shell interacts with its operators by awaiting HTTP requests containing a header field named X-siLock-Comment, which must have a value assigned equal to the password established upon the installation of the web shell. After authenticating with the web shell, operators pass commands to the web shell that can:

- Retrieve Microsoft Azure system settings and enumerate the underlying SQL database.

- Store a string sent by the operator and then retrieve a file with a name matching the string from the MOVEit Transfer system.

- Create a new administrator privileged account with a randomly generated username and LoginName and RealName values set to “Health Check Service.”

- Delete an account with LoginName and RealName values set to ‘Health Check Service.’

Progress Software announced the discovery of CVE-2023-34362 MOVEit Transfer vulnerability and issued guidance on known affected versions, software upgrades, and patching. Based on evidence of active exploitation, CISA added this vulnerability to the Known Exploited Vulnerabilities (KEVs) Catalog on June 2, 2023. This MOVEit Transfer critical vulnerability exploit impacts the following versions of the software [2]:

- MOVEit Transfer 2023.0.0

- MOVEit Transfer 2022.1.x

- MOVEit Transfer 2022.0.x

- MOVEit Transfer 2021.1.x

- MOVEit Transfer 2021.0.x

- MOVEit Transfer 2020.1.x

- MOVEit Transfer 2020.0.x

Due to the speed and ease TA505 has exploited this vulnerability, and based on their past campaigns, FBI and CISA expect to see widespread exploitation of unpatched software services in both private and public networks. For IOCs related to the MOVEit campaign, see table 2.
