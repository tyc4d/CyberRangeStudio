# CISA AA24-046A — Threat Actor Leverages Compromised Account of Former Employee to Access State Government Organization

> - Publisher: CISA and MS-ISAC, Joint Cybersecurity Advisory, Product ID AA24-046A, February 15, 2024 (TLP:CLEAR)
> - Web page: https://www.cisa.gov/news-events/cybersecurity-advisories/aa24-046a
> - PDF: https://www.cisa.gov/sites/default/files/2024-02/aa24-046a-threat-actor-leverages-compromised%20account-of%20former-employee.pdf
> - PDF SHA-256: 55534abb402001e831734b065f78d5c8ba6dcaec599fd458c5b3745304261649 (`source.pdf`, 10 pages)
> - License: U.S. Government work, TLP:CLEAR
> - Scope of this file: SUMMARY and TECHNICAL DETAILS (advisory pages 1–4), verbatim. The "Actions to take today" sidebar, ATT&CK tables and mitigations are in `source.pdf.txt`. Table 1 is re-laid-out as a markdown table with the same cell text.
> - Retrieved: 2026-11-15
> - Wording: the text below is the source's own wording; only page furniture, layout indentation and line wrapping were removed (see `reports/overnight/evidence/cti-research/build_reports.py`).

## SUMMARY

The Cybersecurity and Infrastructure Security Agency (CISA) and the Multi-State Information Sharing & Analysis Center (MS-ISAC) conducted an incident response assessment of a state government organization’s network environment after documents containing host and user information, including metadata, were posted on a dark web brokerage site. Analysis confirmed that an unidentified threat actor compromised network administrator credentials through the account of a former employee—a technique commonly leveraged by threat actors—to successfully authenticate to an internal virtual private network (VPN) access point, further navigate the victim’s on-premises environment, and execute various lightweight directory access protocol (LDAP) queries against a domain controller.[1] Analysis also focused on the victim’s Azure environment, which hosts sensitive systems and data, as well as the compromised on- premises environment. Analysis determined there were no indications the threat actor further compromised the organization by moving laterally from the on-premises environment to the Azure environment.

CISA and MS-ISAC are releasing this Cybersecurity Advisory (CSA) to provide network defenders with the tactics, techniques, and procedures (TTPs) used by the threat actor and methods to protect against similar exploitation of both unnecessary and privileged accounts.

## TECHNICAL DETAILS

Note: This advisory uses the MITRE ATT&CK for Enterprise framework, version 14. See the MITRE ATT&CK Tactics and Techniques section for a table of the threat actor’s activity mapped to MITRE ATT&CK® tactics and techniques. For assistance with mapping malicious cyber activity to the MITRE ATT&CK framework, see CISA and MITRE ATT&CK’s Best Practices for MITRE ATT&CK Mapping and CISA’s Decider Tool.

### Overview

A state government organization was notified that documents containing host and user information, including metadata, were posted on a dark web brokerage site. After further investigation, the victim organization determined that the documents were accessed via the compromised account of a former employee. Threat actors commonly leverage valid accounts, including accounts of former employees that have not been properly removed from the Active Directory (AD), to gain access to organizations.[1] CISA and MS-ISAC assessed that an unidentified threat actor likely accessed documents containing host and user information to post on the dark web for profit after gaining access through the account of a former employee. The scope of this investigation included the victim organization’s on-premises environment, as well as their Azure environment, which hosts sensitive systems and data. Analysis determined the threat actor did not move laterally from the compromised on-premises network to the Azure environment and did not compromise sensitive systems.

### Untitled Goose Tool

Incident responders collected Azure and Microsoft Defender for Endpoint (MDE) logs using CISA’s Untitled Goose Tool—a free tool to help network defenders detect potentially malicious activity in Microsoft Azure, Azure Active Directory (AAD), and Microsoft 365 (M365) environments. CISA developed the Untitled Goose Tool to export and review AAD sign-in and audit logs, M365 unified audit logs (UAL), Azure activity logs, and MDE data. By exporting cloud artifacts, Untitled Goose Tool supports incident response teams with environments that do not ingest logs into a security information and event management (SIEM) tool.

### Threat Actor Activity

The logs revealed the threat actor first connected from an unknown virtual machine (VM) to the victim’s on-premises environment via internet protocol (IP) addresses within their internal VPN range. CISA and MS-ISAC assessed that the threat actor connected to the VM through the victim’s VPN [T1133] with the intent to blend in with legitimate traffic to evade detection.

#### Initial Access: Compromised Domain Accounts

USER1: The threat actor gained initial access through the compromised account of a former employee with administrative privileges (USER1) [T1078.002] to conduct reconnaissance and discovery activities. The victim organization confirmed that this account was not disabled immediately following the employee’s departure.

- The threat actor likely obtained the USER1 account credentials in a separate data breach due to the credentials appearing in publicly available channels containing leaked account information [T1589.001].

- USER1 had access to two virtualized servers including SharePoint and the workstation of the former employee. The workstation was virtualized from a physical workstation using the Veeam Physical to Virtual (P2V) function within the backup software.

USER2: The threat actor likely obtained the USER2 account credentials from the virtualized SharePoint server managed by USER1 [T1213.002]. The victim confirmed that the administrator credentials for USER2 were stored locally on this server [T1552.001].

- Through connection from the VM, the threat actor authenticated to multiple services [T1021] via the USER1 account, as well as from an additional compromised global domain administrator account (USER2) [T1078.002].

- The threat actor’s use of the USER2 account was impactful due to the access it granted to both the on-premises AD and Azure AD [T1021.007], thus enabling administrative privileges [T1078.004].

Following notification of the dark web posting, the victim organization immediately disabled the USER1 account and took the two virtualized servers associated with the former employee offline. The victim also changed the password for the USER2 account and removed administrator privileges. Neither of the administrative accounts had multifactor authentication (MFA) enabled.

#### LDAP Queries

Through connection from the VM, the threat actor conducted LDAP queries of the AD, likely using the open source tool AdFind.exe, based on the format of the output. CISA and MS-ISAC assess the threat actor executed the LDAP queries [T1087.002] to collect user, host [T1018], and trust relationship information [T1482]. It is also believed the LDAP queries generated the text files the threat actor posted for sale on the dark web brokerage site: ad_users.txt, ad_computers.txt, and trustdmp.txt. Table 1 lists all queries that were conducted between 08:39:43-08:40:56 Coordinated Universal Time (UTC).

Table 1: LDAP Queries Conducted by the Threat Actor

| Query | Description |
|---|---|
| LDAP Search Scope: WholeSubtree, Base Object: dc=[REDACTED],dc=local, Search Filter: (objectCategory=CN=Person,CN=Schema,CN=Configuration,DC=[REDACTED],DC=local) | Collects names and metadata of users in the domain. |
| LDAP Search Scope: WholeSubtree, Base Object: dc=[REDACTED],dc=local, Search Filter: (objectCategory=CN=Computer,CN=Schema,CN=Configuration,DC=[REDACTED],DC=local) | Collects names and metadata of hosts in the domain. |
| LDAP Search Scope: WholeSubtree, Base Object: dc=[REDACTED],dc=local, Search Filter: (objectCategory=CN=Trusted-Domain,CN=Schema,CN=Configuration,DC=[REDACTED],DC=local) | Collects trust information in the domain. |
| LDAP Search Scope: WholeSubtree, Base Object: DC=[REDACTED],DC=local, Search Filter: ( & ( & (sAMAccountType=805306368) (servicePrincipalName=*) ( ! (sAMAccountName=krbtgt) ) ( ! (userAccountControl&2) ) ) (adminCount=1) ) | Collects Domain Administrators and Service Principals in the domain. |

#### Service Authentication

Through the VM connection, the threat actor was observed authenticating to various services on the victim organization’s network from the USER1 and USER2 administrative accounts. In all instances, the threat actor authenticated to the Common Internet File Service (CIFS) on various endpoints [T1078.002],[T1021.002]—a protocol used for providing shared access to files and printers between machines on the network. This was likely used for file, folder, and directory discovery [T1083], and assessed to be executed in an automated manner.

- USER1 authenticated to four services, presumably for the purpose of network and service discovery [T1046].

- USER2 authenticated to twelve services. Note: This account had administrative privileges to both the on-premises network and Azure tenant.
