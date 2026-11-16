# Scattered Spider

> - Publisher: FBI Internet Crime Complaint Center (IC3), CSA listing — advisory id AA23-320A
> - Date: 2023-11-16
> - URL: https://www.ic3.gov/CSA/2023/231116.pdf
> - PDF SHA-256: ff79a5fd8c2215170fd7256bdc7c545a822d80062d9ce2a3ea7feb60200a6344 (`source.pdf`, 14 pages)
> - Rights: published by U.S. government agencies (FBI IC3 copy); rule scan in `reports/eval/build_corpus.py` found no non-US copyright or licence notice. Some are joint advisories with non-US co-authors; public-domain status of co-authored parts not determined.
> - Text: `pdftotext -layout` output; only page furniture removed by `reports/eval/build_corpus.py` (28 lines). No other edits.

Co-Authored by:                                                                                                Product ID: AA23-320A
                                                                                                                 November 16, 2023


        Scattered Spider
        SUMMARY
        The Federal Bureau of Investigation (FBI) and Cybersecurity              Actions to take today to mitigate
        and Infrastructure Security Agency (CISA) are releasing this             malicious cyber activity:
        joint Cybersecurity Advisory (CSA) in response to recent                    Maintain offline backups of data.
        activity by Scattered Spider threat actors against the                      Enable and enforce phishing-
        commercial facilities sectors and subsectors. This advisory                  resistant multifactor
        provides tactics, techniques, and procedures (TTPs)                          authentication (MFA).
        obtained through FBI investigations as recently as November                 Implementing application
        2023.                                                                        controls to manage and control
        Scattered Spider is a cybercriminal group that targets large                 software execution.
        companies and their contracted information technology (IT)
        help desks. Scattered Spider threat actors, per trusted third parties, have typically engaged in data theft
        for extortion and have also been known to utilize BlackCat/ALPHV ransomware alongside their usual
        TTPs.
        The FBI and CISA encourage critical infrastructure organizations to implement the recommendations
        in the Mitigations section of this CSA to reduce the likelihood and impact of a cyberattack by
        Scattered Spider actors.

        TECHNICAL DETAILS
        Note: This advisory uses the MITRE ATT&CK for Enterprise framework, version 14. See the MITRE
        ATT&CK® Tactics and Techniques section for a table of the threat actors’ activity mapped to MITRE
        ATT&CK tactics and techniques. For assistance with mapping malicious cyber activity to the MITRE
        ATT&CK framework, see CISA and MITRE ATT&CK’s Best Practices for MITRE ATT&CK Mapping
        and CISA’s Decider Tool.
        Overview


        To report suspicious or criminal activity related to information found in this joint Cybersecurity Advisory, contact
        your local FBI field office or CISA’s 24/7 Operations Center at Report@cisa.gov or (888) 282-0870. When
        available, please include the following information regarding the incident: date, time, and location of the incident;
        type of activity; number of people affected; type of equipment used for the activity; the name of the submitting
        company or organization; and a designated point of contact.
        This document is distributed as TLP:CLEAR. Sources may use TLP:CLEAR when information carries minimal or
        no foreseeable risk of misuse, in accordance with applicable rules and procedures for public release. Subject to
        standard copyright rules. TLP:CLEAR information may be distributed without restrictions. For more information
        on the Traffic Light Protocol, see cisa.gov/tlp.

TLP:CLEAR                                                                                                     FBI  CISA


       Scattered Spider (also known as Starfraud, UNC3944, Scatter Swine, and Muddled Libra) engages in
       data extortion and several other criminal activities.[1] Scattered Spider threat actors are considered
       experts in social engineering and use multiple social engineering techniques, especially phishing,
       push bombing, and subscriber identity module (SIM) swap attacks, to obtain credentials, install
       remote access tools, and/or bypass multi-factor authentication (MFA). According to public reporting,
       Scattered Spider threat actors have [2],[3],[4]:
               Posed as company IT and/or helpdesk staff using phone calls or SMS messages to obtain
                credentials from employees and gain access to the network [T1598],[T1656].
               Posed as company IT and/or helpdesk staff to direct employees to run commercial remote
                access tools enabling initial access [T1204],[T1219],[T1566].
               Posed as IT staff to convince employees to share their one-time password (OTP), an MFA
                authentication code.
               Sent repeated MFA notification prompts leading to employees pressing the “Accept” button
                (also known as MFA fatigue) [T1621].[5]
               Convinced cellular carriers to transfer control of a targeted user’s phone number to a SIM card
                they controlled, gaining control over the phone and access to MFA prompts.
               Monetized access to victim networks in numerous ways including extortion enabled by
                ransomware and data theft [T1657].
       After gaining access to networks, FBI observed Scattered Spider threat actors using publicly
       available, legitimate remote access tunneling tools. Table 1 details a list of legitimate tools Scattered
       Spider, repurposed and used for their criminal activity. Note: The use of these legitimate tools alone
       is not indicative of criminal activity. Users should review the Scattered Spider indicators of
       compromise (IOCs) and TTPs discussed in this CSA to determine whether they have been
       compromised.

                                        Table 1: Legitimate Tools Used by Scattered Spider

        Tool                       Intended Use

        Fleetdeck.io               Enables remote monitoring and management of systems.

        Level.io                   Enables remote monitoring and management of systems.

        Mimikatz [S0002]           Extracts credentials from a system.

        Ngrok [S0508]              Enables remote access to a local web server by tunneling over the internet.

        Pulseway                   Enables remote monitoring and management of systems.

        Screenconnect              Enables remote connections to network devices for management.

        Splashtop                  Enables remote connections to network devices for management.


TLP:CLEAR                                                                                                      FBI  CISA


        Tool                       Intended Use

        Tactical.RMM               Enables remote monitoring and management of systems.

        Tailscale                  Provides virtual private networks (VPNs) to secure network communications.

        Teamviewer                 Enables remote connections to network devices for management.


       In addition to using legitimate tools, Scattered Spider also uses malware as part of its TTPs. See
       Table 2 for some of the malware used by Scattered Spider.

                                           Table 2: Malware Used by Scattered Spider

        Malware                                 Use

        AveMaria (also known as
                                                Enables remote access to a victim’s systems.
        WarZone [S0670])

                                                Steals information including login credentials [TA0006],
        Raccoon Stealer
                                                browser history [T1217], cookies [T1539], and other data.

                                                Steals information including login credentials, browser history,
        VIDAR Stealer
                                                cookies, and other data.


       Scattered Spider threat actors have historically evaded detection on target networks by using living off
       the land techniques and allowlisted applications to navigate victim networks, as well as frequently
       modifying their TTPs.
       Observably, Scattered Spider threat actors have exfiltrated data [TA0010] after gaining access and
       threatened to release it without deploying ransomware; this includes exfiltration to multiple sites
       including U.S.-based data centers and MEGA[.]NZ [T1567.002].
       Recent Scattered Spider TTPs
       New TTP - File Encryption
       More recently, the FBI has identified Scattered Spider threat actors now encrypting victim files after
       exfiltration [T1486]. After exfiltrating and/or encrypting data, Scattered Spider threat actors
       communicate with victims via TOR, Tox, email, or encrypted applications.
       Reconnaissance, Resource Development, and Initial Access
       Scattered Spider intrusions often begin with broad phishing [T1566] and smishing [T1660] attempts
       against a target using victim-specific crafted domains, such as the domains listed in Table 3
       [T1583.001].


TLP:CLEAR                                                                                                     FBI  CISA

                                       Table 3: Domains Used by Scattered Spider Threat Actors

        Domains

        victimname-sso[.]com

        victimname-servicedesk[.]com

        victimname-okta[.]com


       In most instances, Scattered Spider threat actors conduct SIM swapping attacks against users that
       respond to the phishing/smishing attempt. The threat actors then work to identify the personally
       identifiable information (PII) of the most valuable users that succumbed to the phishing/smishing,
       obtaining answers for those users’ security questions. After identifying usernames, passwords, PII
       [T1589], and conducting SIM swaps, the threat actors then use social engineering techniques [T1656]
       to convince IT help desk personnel to reset passwords and/or MFA tokens
       [T1078.002],[T1199],[T1566.004] to perform account takeovers against the users in single sign-on
       (SSO) environments.
       Execution, Persistence, and Privilege Escalation
       Scattered Spider threat actors then register their own MFA tokens [T1556.006],[T1606] after
       compromising a user’s account to establish persistence [TA0003]. Further, the threat actors add a
       federated identity provider to the victim’s SSO tenant and activate automatic account linking
       [T1484.002]. The threat actors are then able to sign into any account by using a matching SSO
       account attribute. At this stage, the Scattered Spider threat actors already control the identity provider
       and then can choose an arbitrary value for this account attribute. As a result, this activity allows the
       threat actors to perform privileged escalation [TA0004] and continue logging in even when passwords
       are changed [T1078]. Additionally, they leverage common endpoint detection and response (EDR)
       tools installed on the victim networks to take advantage of the tools’ remote-shell capabilities and
       executing of commands which elevates their access. They also deploy remote monitoring and
       management (RMM) tools [T1219] to then maintain persistence.
       Discovery, Lateral Movement, and Exfiltration
       Once persistence is established on a target network, Scattered Spider threat actors often perform
       discovery, specifically searching for SharePoint sites [T1213.002], credential storage documentation
       [T1552.001], VMware vCenter infrastructure [T1018], backups, and instructions for setting up/logging
       into Virtual Private Networks (VPN) [TA0007]. The threat actors enumerate the victim’s Active
       Directory (AD), perform discovery and exfiltration of victim’s code repositories [T1213.003], code-
       signing certificates [T1552.004], and source code [T1083],[TA0010]. Threat actors activate Amazon
       Web Services (AWS) Systems Manager Inventory [T1538] to discover targets for lateral movement
       [TA0007],[TA0008], then move to both preexisting [T1021.007] and actor-created [T1578.002]
       Amazon Elastic Compute Cloud (EC2) instances. In instances where the ultimate goal is data
       exfiltration, Scattered Spider threat actors use actor-installed extract, transform, and load (ETL) tools


TLP:CLEAR                                                                                                     FBI  CISA


       [T1648] to bring data from multiple data sources into a centralized database [T1074],[T1530].
       According to trusted third parties, where more recent incidents are concerned, Scattered Spider threat
       actors may have deployed BlackCat/ALPHV ransomware onto victim networks—thereby encrypting
       VMware Elastic Sky X integrated (ESXi) servers [T1486].
       To determine if their activities have been uncovered and maintain persistence, Scattered Spider
       threat actors often search the victim’s Slack, Microsoft Teams, and Microsoft Exchange online for
       emails [T1114] or conversations regarding the threat actor’s intrusion and any security response. The
       threat actors frequently join incident remediation and response calls and teleconferences, likely to
       identify how security teams are hunting them and proactively develop new avenues of intrusion in
       response to victim defenses. This is sometimes achieved by creating new identities in the
       environment [T1136] and is often upheld with fake social media profiles [T1585.001] to backstop
       newly created identities.

       MITRE ATT&CK TACTICS AND TECHNIQUES
       See Tables 4 through 17 for all referenced threat actor tactics and techniques in this advisory.

                                                Table 4: Reconnaissance

        Technique Title                         ID                                Use

        Gather Victim Identity                            Scattered Spider threat actors gather usernames,
                                             T1589
        Information                                       passwords, and PII for targeted organizations.

                                                          Scattered Spider threat actors use phishing to
        Phishing for Information             T1598        obtain login credentials, gaining access to a
                                                          victim’s network.

                                            Table 5: Resource Development

        Technique Title                         ID                                Use

                                                          Scattered Spider threat actors create domains for
        Acquire Infrastructure:
                                           T1583.001      use in phishing and smishing attempts against
        Domains
                                                          targeted organizations.

                                                          Scattered Spider threat actors create fake social
        Establish Accounts: Social
                                           T1585.001      media profiles to backstop newly created user
        Media Accounts
                                                          accounts in a targeted organization.


TLP:CLEAR                                                                                                   FBI  CISA


                                            Table 6: Initial Access

        Technique Title                    ID                                  Use

                                                        Scattered Spider threat actors use broad phishing
                                                        attempts against a target to obtain information
                                                        used to gain initial access.
        Phishing                         T1566
                                                        Scattered Spider threat actors have posed as
                                                        helpdesk personnel to direct employees to install
                                                        commercial remote access tools.

                                                        Scattered Spider threat actors send SMS
        Phishing (Mobile)                T1660          messages, known as smishing, when targeting a
                                                        victim.

                                                        Scattered Spider threat actors use voice
        Phishing: Spearphishing Voice   T1566.004       communications to convince IT help desk
                                                        personnel to reset passwords and/or MFA tokens.

                                                        Scattered Spider threat actors abuse trusted
        Trusted Relationship             T1199          relationships of contracted IT help desks to gain
                                                        access to targeted organizations.

                                                        Scattered Spider threat actors obtain access to
        Valid Accounts: Domain
                                        T1078.002       valid domain accounts to gain initial access to a
        Accounts
                                                        targeted organization.

                                                Table 7: Execution

        Technique Title                    ID                                  Use

                                                        Scattered Spider threat actors use ETL tools to
        Serverless Execution             T1648
                                                        collect data in cloud environments.

                                                        Scattered Spider threat actors impersonating
                                                        helpdesk personnel direct employees to run
        User Execution                   T1204
                                                        commercial remote access tools thereby enabling
                                                        access to the victim’s network.


TLP:CLEAR                                                                                                  FBI  CISA


                                               Table 8: Persistence

        Technique Title                     ID                                  Use

                                                        Scattered Spider threat actors seek to maintain
        Persistence                       TA0003
                                                        persistence on a targeted organization’s network.

                                                        Scattered Spider threat actors create new user
        Create Account                    T1136
                                                        identities in the targeted organization.

        Modify Authentication Process:                  Scattered Spider threat actors may modify MFA
                                         T1556.006
        Multi-Factor Authentication                     tokens to gain access to a victim’s network.

                                                        Scattered Spider threat actors abuse and control
        Valid Accounts                    T1078         valid accounts to maintain network access even
                                                        when passwords are changed.

                                           Table 9: Privilege Escalation

        Technique Title                     ID                                  Use

                                                        Scattered Spider threat actors escalate account
        Privilege Escalation              TA0004        privileges when on a targeted organization’s
                                                        network.

                                                        Scattered Spider threat actors add a federated
        Domain Policy Modification:
                                         T1484.002      identify provider to the victim’s SSO tenant and
        Domain Trust Modification
                                                        activate automatic account linking.

                                           Table 10: Defense Evasion

        Technique Title                     ID                                  Use

        Modify Cloud Compute                            Scattered Spider threat actors will create cloud
        Infrastructure: Create Cloud     T1578.002      instances for use during lateral movement and
        Instance                                        data collection.

                                                        Scattered Spider threat actors pose as company
                                                        IT and/or helpdesk staff to gain access to victim’s
                                                        networks.
        Impersonation                     TA1656
                                                        Scattered Spider threat actors use social
                                                        engineering to convince IT help desk personnel to
                                                        reset passwords and/or MFA tokens.


TLP:CLEAR                                                                                                    FBI  CISA


                                          Table 11: Credential Access

        Technique Title                    ID                                  Use

                                                      Scattered Spider threat actors use tools, such as
        Credential Access                TA0006
                                                      Raccoon Stealer, to obtain login credentials.

                                                      Scattered Spider threat actors may forge MFA
        Forge Web Credentials            T1606
                                                      tokens to gain access to a victim’s network.

                                                      Scattered Spider sends repeated MFA notification
        Multi-Factor Authentication
                                         T1621        prompts to lead employees to accept the prompt
        Request Generation
                                                      and gain access to the target network.

        Unsecured Credentials:                        Scattered Spider threat actors search for
                                        T1552.001
        Credentials in Files                          insecurely stored credentials on victim’s systems.

        Unsecured Credentials:                        Scattered Spider threat actors search for
                                        T1552.004
        Private Keys                                  insecurely stored private keys on victim’s systems.

                                             Table 12: Discovery

        Technique Title                    ID                                  Use

                                                      Upon gaining access to a targeted network,
                                                      Scattered Spider threat actors seek out
                                                      SharePoint sites, credential storage
        Discovery                        TA0007
                                                      documentation, VMware vCenter, infrastructure
                                                      backups and enumerate AD to identify useful
                                                      information to support further operations.

                                                      Scattered Spider threat actors use tools (e.g.,
        Browser Information Discovery    T1217
                                                      Raccoon Stealer) to obtain browser histories.

                                                      Scattered Spider threat actors leverage AWS
        Cloud Service Dashboard          T1538        Systems Manager Inventory to discover targets for
                                                      lateral movement.

                                                      Scattered Spider threat actors search a
        File and Directory Discovery     T1083        compromised network to discover files and
                                                      directories for further information or exploitation.

                                                      Scattered Spider threat actors search for
        Remote System Discovery          T1018
                                                      infrastructure, such as remote systems, to exploit.


TLP:CLEAR                                                                                                 FBI  CISA


        Technique Title                   ID                                  Use

                                                     Scattered Spider threat actors use tools, such as
        Steal Web Session Cookie        T1539
                                                     Raccoon Stealer, to obtain browser cookies.

                                         Table 13: Lateral Movement

        Technique Title                   ID                                  Use

                                                     Scattered Spider threat actors laterally move
        Lateral Movement                TA0008       across a target network upon gaining access and
                                                     establishing persistence.

                                                     Scattered Spider threat actors use pre-existing
        Remote Services: Cloud
                                       T1021.007     cloud instances for lateral movement and data
        Services
                                                     collection.

                                            Table 14: Collection

        Technique Title                   ID                                  Use

        Data from Information
                                                     Scattered Spider threat actors search code
        Repositories: Code             T1213.003
                                                     repositories for data collection and exfiltration.
        Repositories

        Data from Information                        Scattered Spider threat actors search SharePoint
                                       T1213.002
        Repositories: Sharepoint                     repositories for information.

                                                     Scattered Spider threat actors stage data from
        Data Staged                     T1074        multiple data sources into a centralized database
                                                     before exfiltration.

                                                     Scattered Spider threat actors search victim’s
        Email Collection                T1114        emails to determine if the victim has detected the
                                                     intrusion and initiated any security response.

                                                     Scattered Spider threat actors search data in
        Data from Cloud Storage         T1530
                                                     cloud storage for collection and exfiltration.


TLP:CLEAR                                                                                                              FBI  CISA


                                                  Table 15: Command and Control

                 Technique Title                       ID                                 Use

                                                                   Impersonating helpdesk personnel, Scattered
                                                                   Spider threat actors direct employees to run
                                                                   commercial remote access tools thereby enabling
                                                                   access to and command and control of the victim’s
        Remote Access Software                      T1219          network.
                                                                   Scattered Spider threat actors leverage third-party
                                                                   software to facilitate lateral movement and
                                                                   maintain persistence on a target organization’s
                                                                   network.

                                                         Table 16: Exfiltration

            Technique Title                       ID                                      Use

                                                                   Scattered Spider threat actors exfiltrate data from
        Exfiltration                            TA0010
                                                                   a target network to for data extortion.

                                                            Table 17: Impact

            Technique Title                       ID                                      Use

                                                                   Scattered Spider threat actors recently began
                                                                   encrypting data on a target network and
        Data Encrypted for
                                        T1486                      demanding a ransom for decryption.
        Impact
                                                                   Scattered Spider threat actors has been observed
                                                                   encrypting VMware ESXi servers.

        Exfiltration Over Web                                      Scattered Spider threat actors exfiltrate data to
        Service: Exfiltration to        T1567.002                  multiple sites including U.S.-based data centers
        Cloud Storage                                              and MEGA[.]NZ.

                                                                   Scattered Spider threat actors monetized access
        Financial Theft                 T1657                      to victim networks in numerous ways including
                                                                   extortion-enabled ransomware and data theft.


TLP:CLEAR                                                                                                FBI  CISA


       MITIGATIONS
        The FBI and CISA recommend organizations
                                                               These mitigations apply to all critical
       implement the mitigations below to improve your
                                                               infrastructure organizations and network
       organization’s cybersecurity posture based on the
                                                               defenders. The FBI and CISA recommend
       threat actor activity and to reduce the risk of
                                                               that software manufactures incorporate
       compromise by Scattered Spider threat actors. These
                                                               secure-by-design and -default principles
       mitigations align with the Cross-Sector Cybersecurity
                                                               and tactics into their software development
       Performance Goals (CPGs) developed by CISA and
                                                               practices limiting the impact of ransomware
       the National Institute of Standards and Technology
                                                               techniques, thus, strengthening the secure
       (NIST). The CPGs provide a minimum set of practices
                                                               posture for their customers.
       and protections that CISA and NIST recommend all
       organizations implement. CISA and NIST based the        For more information on secure by design,
       CPGs on existing cybersecurity frameworks and           see CISA’s Secure by Design and Default
       guidance to protect against the most common and         webpage and joint guide.
       impactful threats, tactics, techniques, and procedures.
       Visit CISA’s Cross-Sector Cybersecurity Performance Goals for more information on the CPGs,
       including additional recommended baseline protections.
               Implement application controls to manage and control execution of software, including
                allowlisting remote access programs. Application controls should prevent installation and
                execution of portable versions of unauthorized remote access and other software. A properly
                configured application allowlisting solution will block any unlisted application execution.
                Allowlisting is important because antivirus solutions may fail to detect the execution of
                malicious portable executables when the files use any combination of compression,
                encryption, or obfuscation.
               Reduce threat of malicious actors using remote access tools by:
                o Auditing remote access tools on your network to identify currently used and/or
                    authorized software.
                o Reviewing logs for execution of remote access software to detect abnormal use of
                    programs running as a portable executable [CPG 2.T].
                o Using security software to detect instances of remote access software being loaded only
                    in memory.
                o Requiring authorized remote access solutions to be used only from within your network
                    over approved remote access solutions, such as virtual private networks (VPNs) or virtual
                    desktop interfaces (VDIs).
                o Blocking both inbound and outbound connections on common remote access
                    software ports and protocols at the network perimeter.
                o Applying recommendations in the Guide to Securing Remote Access Software.
               Implementing FIDO/WebAuthn authentication or Public Key Infrastructure (PKI)-based
                MFA. These MFA implementations are resistant to phishing and not suspectable to push
                bombing or SIM swap attacks, which are techniques known to be used by Scattered Spider
                actors. See CISA’s fact sheet Implementing Phishing-Resistant MFA for more information.


TLP:CLEAR                                                                                                     FBI  CISA


               Strictly limit the use of Remote Desktop Protocol (RDP) and other remote desktop
                services. If RDP is necessary, rigorously apply best practices, for example [CPG 2.W]:
                o Audit the network for systems using RDP.
                o Close unused RDP ports.
                o Enforce account lockouts after a specified number of attempts.
                o Apply phishing-resistant multifactor authentication (MFA).
                o Log RDP login attempts.
       In addition, the authoring authorities of this CSA recommend network defenders apply the following
       mitigations to limit potential adversarial use of common system and network discovery techniques,
       and to reduce the impact and risk of compromise by ransomware or data extortion actors:
            Implement a recovery plan to maintain and retain multiple copies of sensitive or proprietary
               data and servers in a physically separate, segmented, and secure location (i.e., hard drive,
               storage device, the cloud).
            Maintain offline backups of data and regularly maintain backup and restoration (daily or
               weekly at minimum). By instituting this practice, an organization limits the severity of disruption
               to its business practices [CPG 2.R].
            Require all accounts with password logins (e.g., service account, admin accounts, and
               domain admin accounts) to comply with NIST's standards for developing and managing
               password policies.
               o Implement password policies in compliance with NIST’s standards.
               o Use “strong” passwords that are unique and random, as well as contain at least sixteen
                    characters and no more than 64 characters in length [CPG 2.B].
               o Consider implementing industry-recognized password managers that align with
                    organizational technology procurement policies.
               o Avoid reusing passwords [CPG 2.C].
               o Implement multiple failed login attempt account lockouts [CPG 2.G].
               o Disable password “hints.”
               o Refrain from requiring recurring password changes.
                    Note: NIST guidance suggests favoring longer passwords instead of requiring regular and
                    frequent password resets. Frequent password resets are more likely to result in users
                    developing password “patterns” cyber criminals can easily decipher.
               o Require administrator credentials to install software.
            Require phishing-resistant multifactor authentication (MFA) for all services to the extent
               possible, particularly for webmail, virtual private networks (VPNs), and accounts that access
               critical systems [CPG 2.H].
            Keep all operating systems, software, and firmware up to date. Timely patching is one of
               the most efficient and cost-effective steps an organization can take to minimize its exposure to
               cybersecurity threats. Prioritize patching known exploited vulnerabilities in internet-facing
               systems [CPG 1.E].
            Segment networks to prevent the spread of ransomware. Network segmentation can help
               prevent the spread of ransomware by controlling traffic flows between—and access to—
               various subnetworks and by restricting adversary lateral movement [CPG 2.F].


TLP:CLEAR                                                                                                  FBI  CISA


               Identify, detect, and investigate abnormal activity and potential traversal of the
                indicated ransomware with a networking monitoring tool. To aid in detecting the
                ransomware, implement a tool that logs and reports all network traffic and activity, including
                lateral movement, on a network. Endpoint detection and response (EDR) tools are particularly
                useful for detecting lateral connections as they have insight into common and uncommon
                network connections for each host [CPG 3.A].
               Install, regularly update, and enable real time detection for antivirus software on all
                hosts.
               Disable unused ports and protocols [CPG 2.V].
               Consider adding an email banner to emails received from outside your organization [CPG
                2.M].
               Disable hyperlinks in received emails.
               Ensure all backup data is encrypted, immutable (i.e., ensure backup data cannot be
                altered or deleted), and covers the entire organization’s data infrastructure [CPG 2.K, 2.L,
                2.R].

       VALIDATE SECURITY CONTROLS
       In addition to applying mitigations, FBI and CISA recommend exercising, testing, and validating your
       organization's security program against the threat behaviors mapped to the MITRE ATT&CK for
       Enterprise framework in this advisory. The FBI and CISA recommend testing your existing security
       controls inventory to assess how they perform against the ATT&CK techniques described in this
       advisory.
       To get started:
           1. Select an ATT&CK technique described in this advisory (see Tables 4-17).
           2. Align your security technologies against the technique.
           3. Test your technologies against the technique.
           4. Analyze your detection and prevention technologies’ performance.
           5. Repeat the process for all security technologies to obtain a set of comprehensive performance
              data.
           6. Tune your security program, including people, processes, and technologies, based on the
              data generated by this process.
       FBI and CISA recommend continually testing your security program, at scale, in a production
       environment to ensure optimal performance against the MITRE ATT&CK techniques identified in this
       advisory.

       REPORTING
       The FBI and CISA are seeking any information that can be shared, to include a sample ransom note,
       communications with Scattered Spider group actors, Bitcoin wallet information, decryptor files, and/or
       a benign sample of an encrypted file. The FBI and CISA do not encourage paying ransom as
       payment does not guarantee victim files will be recovered. Furthermore, payment may also embolden
       adversaries to target additional organizations, encourage other criminal actors to engage in the


TLP:CLEAR                                                                                                  FBI  CISA


       distribution of ransomware, and/or fund illicit activities. Regardless of whether you or your
       organization have decided to pay the ransom, FBI and CISA urge you to promptly report ransomware
       incidents to a local FBI Field Office, report the incident to the FBI Internet Crime Complaint Center
       (IC3) at IC3.gov, or CISA via CISA’s 24/7 Operations Center (report@cisa.gov or 888-282-0870).

       REFERENCES
       [1] MITRE ATT&CK – Scattered Spider
       [2] Trellix - Scattered Spider: The Modus Operandi
       [3] Crowdstrike - Not a SIMulation: CrowdStrike Investigations Reveal Intrusion Campaign Targeting
       Telco and BPO Companies
       [4] Crowdstrike - SCATTERED SPIDER Exploits Windows Security Deficiencies with Bring-Your-
       Own-Vulnerable-Driver Tactic in Attempt to Bypass Endpoint Security
       [5] Malwarebytes - Ransomware group steps up, issues statement over MGM Resorts compromise

       DISCLAIMER
       The information in this report is being provided “as is” for informational purposes only. The FBI and
       CISA do not endorse any commercial entity, product, company, or service, including any entities,
       products, or services linked within this document. Any reference to specific commercial entities,
       products, processes, or services by service mark, trademark, manufacturer, or otherwise, does not
       constitute or imply endorsement, recommendation, or favoring by FBI and CISA.

       VERSION HISTORY
       November 16, 2023: Initial version.
       November 21, 2023: Updated password recommendation language on page 12.
