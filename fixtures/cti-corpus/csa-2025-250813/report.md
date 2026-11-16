# Foundations for OT Cybersecurity: Asset Inventory Guidance for Owners and Operators

> - Publisher: FBI Internet Crime Complaint Center (IC3), CSA listing
> - Date: 2025-08-13
> - URL: https://www.ic3.gov/CSA/2025/250813.pdf
> - PDF SHA-256: a68d0e21b232b6d1f80a8f676f6d573ccc52634e9600c2d6c1347ccce44aaffb (`source.pdf`, 31 pages)
> - Rights: published by U.S. government agencies (FBI IC3 copy); rule scan in `reports/eval/build_corpus.py` found no non-US copyright or licence notice. Some are joint advisories with non-US co-authors; public-domain status of co-authored parts not determined.
> - Text: `pdftotext -layout` output; only page furniture removed by `reports/eval/build_corpus.py` (92 lines). No other edits.

Foundations for OT Cybersecurity: Asset Inventory
Guidance for Owners and Operators

Publication: August 13, 2025
U.S. Cybersecurity and Infrastructure Security Agency          Australian Signals Directorate’s Australian Cyber
U.S. Environmental Protection Agency                           Security Centre
U.S. National Security Agency                                  Canadian Centre for Cyber Security
U.S. Federal Bureau of Investigation                           Germany’s Federal Office for Information Security
                                                               Netherlands’ National Cyber Security Centre
                                                               New Zealand’s National Cyber Security Centre

This document is marked TLP:CLEAR. Disclosure is not limited. Sources may use TLP:CLEAR when information carries
minimal or no foreseeable risk of misuse, in accordance with applicable rules and procedures for public release. Subject
to standard copyright rules, TLP:CLEAR information may be distributed without restriction. For more information on the
Traffic Light Protocol, see Traffic Light Protocol (TLP) Definitions and Usage.

Asset Inventory Guidance for Owners and Operators                                                      TLP:CLEAR


    Executive Summary
    When building a modern defensible architecture, it is essential for operational technology (OT) owners and
    operators across all critical infrastructure sectors to create an OT asset inventory supplemented by an OT
    taxonomy. Using these tools helps owners and operators identify which assets in their environment should
    be secured and protected, and structure their defenses accordingly to reduce the risk a cybersecurity
    incident poses to the organization’s mission and service continuity.
    An asset inventory is an organized, regularly updated list of an organization’s systems, hardware, and
    software. For OT environments, a key part of creating an asset inventory is developing an OT taxonomy: a
    categorization system that organizes and prioritizes OT assets, aids in risk identification, vulnerability
    management, and incident response by classifying assets based on function and criticality.
    This guidance outlines a process for OT owners and operators to create an asset inventory and OT
    taxonomy. This process includes defining scope and objectives for the inventory, identifying assets,
    collecting attributes, creating a taxonomy, managing data, and implementing asset life cycle management.
    These steps define a thorough and systematic approach to creating and maintaining an OT asset inventory
    and OT taxonomy, enabling organizations to maintain an accurate and up-to-date record of their OT assets.
    Furthermore, this guidance outlines how OT owners and operators can maintain, improve, and use their
    asset inventory to protect their most vital assets. Steps include OT cybersecurity and risk management,
    maintenance and reliability, performance monitoring and reporting, training and awareness, and
    continuous improvement. By addressing these areas, organizations can enhance their overall security
    posture and ensure the reliability and safety of their OT environments.
    To illustrate real world examples of OT taxonomies, CISA developed conceptual taxonomies through
    working sessions with organizations in the Energy Sector and Water and Wastewater Sector (see
                                                   39TU               U39T


    Appendix B: Taxonomy for Oil and Gas Organizations , Appendix C: Taxonomy for Electricity Organizations ,
    61T                                                   61T   61T                                              61T


    and Appendix D: Water and Wastewater ). These are not authoritative taxonomies for these sectors but are
          61T                                61T


    meant to help guide sector-specific organizations develop their own asset classification systems.


Asset Inventory Guidance for Owners and Operators                                                                                                                      TLP:CLEAR


    Table of Contents
    Introduction ................................................................................................................................................................... 4
       Acknowledgements ............................................................................................................................................ 6
    OT Taxonomies ............................................................................................................................................................. 6
    Steps to Develop an OT Asset Inventory and Taxonomy ........................................................................................ 8
    Post Inventory and Taxonomy Development Actions .......................................................................................... 11
       OT Cybersecurity and Risk Management ........................................................................................................ 11
       Maintenance and Reliability ............................................................................................................................ 12
       Performance Monitoring and Reporting ......................................................................................................... 13
       Training and Awareness................................................................................................................................... 13
       Continuous Improvement ................................................................................................................................ 13
    Additional Resources ................................................................................................................................................ 13
    Questions and Feedback .......................................................................................................................................... 13
    Contact Information .................................................................................................................................................. 14
    Disclaimer ................................................................................................................................................................... 14
    Version History ........................................................................................................................................................... 14
    Appendix A: Asset Inventory Fields ......................................................................................................................... 15
    Appendix B: Taxonomy for Oil and Gas Organizations ........................................................................................ 19
       Exercise Steps .................................................................................................................................................. 19
    Appendix C: Taxonomy for Electricity Organizations ............................................................................................ 23
       Exercise Steps .................................................................................................................................................. 23
    Appendix D: Water and Wastewater ...................................................................................................................... 27
       Exercise Steps .................................................................................................................................................. 27
    References ................................................................................................................................................................. 31


Asset Inventory Guidance for Owners and Operators                                                                  TLP:CLEAR


    Introduction
     Operational technology (OT) includes a broad set of technologies that covers process automation,
    61T                                       61T


    instrumentation, cyber-physical operations, and industrial control systems (ICS). Many OT systems are
    increasingly connected to business operations and applications that rely on process data and trends
    analysis for operations. If not assembled and integrated securely, these connections can introduce paths
    for cyber actors to move between networks.
    OT is vital to critical infrastructure services like energy production and distribution, as well as water and
    wastewater treatment, making it a prime target for malicious cyber actors seeking to disrupt or destroy
    systems and services or perform other nefarious activities, such as extortion. OT cyber incidents can have
    severe consequences for OT owners and operators, such as financial losses, operational disruptions, and
    compromises of environmental and health and human safety. Cyber actors can cause incidents in multiple
    ways, including exploiting:
               Vulnerabilities in flawed or outdated software/firmware to gain access to OT systems.
              61T             61T


               Weak authentication mechanisms to gain unauthorized access to OT systems.
              61T                                                      61T


             Insufficient network segmentation to move laterally from IT to OT environments and between OT
              61T                                                      61T


              systems.
             Insecure OT protocols to intercept communications, inject malicious commands, and disrupt or
              61T                                    61T


              manipulate industrial processes.
             Insecure remote access points to gain access to OT systems, allowing for lateral movement or for
              61T                                          61T


              command and control.
    Creating an asset inventory is necessary for building a modern defensible architecture and one of CISA’s
    Cybersecurity Performance Goals (CPGs). 1 A modern defensible architecture mitigates risk through a
                                                                 P0F   P


    thoughtful system design and implementation that enables OT cyber defenders to identify, prevent, and
    respond to cyber threats while ensuring reliability, operational continuity, safety, and compliance with
    regulatory requirements. 2 An OT asset inventory —an organized, regularly updated list of an organization’s
                                    P1F   P         61T                      61T


    OT systems, hardware, and software—is foundational to designing a modern defensible architecture
    because without an inventory, organizations do not know what they have and what should be secured and
    protected.
    Developing an asset inventory is a multi-step process where OT owners and operators identify, classify, and
    document assets. OT owners and operators that develop an OT taxonomy as part of the inventory process
                                                                                   61T       61T


    can significantly enhance the process. An OT taxonomy is a categorization system used to organize and
    prioritize OT assets to facilitate risk identification, vulnerability management, and incident response. The


    1 CISA’s CPGs provide a minimum set of practices and protections that CISA and the National Institute of Standards

    and Technology (NIST) recommend all organizations implement. CISA and NIST based the CPGs on existing
    cybersecurity frameworks and guidance to protect against the most common and impactful threats, tactics,
    techniques, and procedures. Visit CISA’s CPGs webpage for more information on the CPGs, including additional
    recommended baseline protections.
    2 For more information on modern defensible architecture, see ASD ACSC’s Modern defensible architecture.


Asset Inventory Guidance for Owners and Operators                                                            TLP:CLEAR


    taxonomy aids owners and operators in conducting asset inventories by facilitating classification of assets
    by function and/or criticality and visualizing asset relationships and dependencies.
    This guide, authored by the Cybersecurity and Infrastructure Security Agency (CISA) and the following
    partners, 3 presents the key elements and best practices for creating an asset inventory as well as industry-
               P2F   P


    accepted approaches for developing an OT taxonomy:
             Environmental Protection Agency (EPA)
             National Security Agency (NSA)
             Federal Bureau of Investigation (FBI)
             Australian Signals Directorate’s Australian Cyber Security Centre (ASD’s ACSC)
             Canadian Centre for Cyber Security (Cyber Centre)
             Germany’s Federal Office for Information Security (BSI)
             Netherlands’ National Cyber Security Centre (NCSC-NL)
             New Zealand’s National Cyber Security Centre (NCSC-NZ)
    This guide emphasizes the importance of proactive planning, collaboration between IT and OT teams, and
    where possible and appropriate, the integration of cutting-edge technologies to stay ahead of potential
    threats. The OT landscape is constantly evolving. This guide is not intended to provide a comprehensive
    view of all possible OT assets. Instead, this document is intended to supplement an organization’s existing
    OT asset inventory resources.
    The guide also contains conceptual taxonomies (see Appendix B: Taxonomy for Oil and Gas Organizations ,
                                                                 61T                                               61T


    Appendix C: Taxonomy for Electricity Organizations , and Appendix D: Water and Wastewater ) developed
    61T                                                    61T         61T                             61T


    through working sessions for oil and gas organizations and electricity organizations in the Energy Sector
    and for Water and Wastewater Sector organizations. CISA created these taxonomies through eight
    collaborative working sessions held in early 2025. CISA collected and incorporated feedback from
    approximately 14 organizations and 33 participants, including representatives from U.S. federal agencies
    and the private sector. These are not authoritative instructions for these sectors but are meant to help
    guide sector-specific organizations that lack widely adopted methods of classifying their OT assets.
    The authoring organizations encourage owners and operators to:
             Review and implement the recommendations in the Steps to Develop an OT Asset Inventory and
                                                                             61T


              Taxonomy section to enhance your asset inventory process.
                         61T


             Socialize this guidance, both within your organization and with your peers.
             Provide feedback on this product and recommendations for future products via CISA’s anonymous
              product survey.


    3 Hereafter referred to as the “authoring agencies.”


Asset Inventory Guidance for Owners and Operators                                                                     TLP:CLEAR


    Acknowledgements
    CISA led the development of this guide through the Joint Cyber Defense Collaborative (JCDC) 4 in        P3F   P


    collaboration the Department of Energy (DOE) and other government and private sector partners, including
    OT owners and operators.
    The following industry stakeholders contributed to the development of this document:
           American Water
           British Petroleum PLC
           Denver Water
           Duke Energy Corporation
           Energy Threat Analysis Center (ETAC) 5    P4F


           Eversource Energy
           James Kimzey Regional Water District
           Lansing Board of Water & Light
           Loudoun Water
           Marathon Petroleum Corporation
           Montgomery Township Municipal Sewer Authority
           Pacific Gas & Electric Company
           Southern California Edison

    OT Taxonomies
    Maintaining an accurate, up-to-date asset inventory is complex. OT environments often contain diverse
    assets, such as legacy systems, specialized devices, sensors, and instrumentation. These assets use
    various proprietary protocols for communication. Owners and operators need context on a components’
    role in monitoring and control of the physical process; this may require owners and operators to physically
    review and inspect assets and associated process areas.


    4 JCDC is a public-private collaborative within CISA that leverages authorities granted by Congress in the 2021

    National Defense Authorization Act (NDAA) to unite the global cyber community in defense of cyberspace.
    5 The U.S. Department of Energy and the private sector established the ETAC for operational collaboration on energy

    sector threat situational awareness, mitigation, and response. The ETAC brings together industry and government
    experts, including the Electricity Information Sharing and Analysis Center (E-ISAC) and national labs, to identify and
    address cyberthreats to the U.S. energy system through work at the unclassified and classified levels.


Asset Inventory Guidance for Owners and Operators                                                             TLP:CLEAR


    Owners and operators should incorporate development of an OT taxonomy into their asset inventory
    process to address this complexity. An OT taxonomy provides a classification methodology for components
    and systems, streamlining the creation and maintenance of the asset inventory. Key benefits of framing an
    OT asset inventory through an OT taxonomy are:


                  Improved        A well-structured OT taxonomy enables effective categorization and organization
                Organization &    of various assets, processes, and data. This makes it easier to manage and
                Management        retrieve information, leading to more efficient operations.


                         Standardizing terminology and classifications helps ensure everyone speaks the same
       Enhanced
     Communication       language. This reduces misunderstandings and improves collaboration between different
                         teams and departments.


                                  With a clear understanding of the relationships and dependencies between
                Better Decision   different assets and processes, organizations can make more informed
                    Making        decisions. This includes optimizing resource allocation, planning maintenance,
                                  and implementing upgrades.


                         By optimizing asset management and reducing inefficiencies, an OT taxonomy can drive
       Cost Savings
                         significant cost savings, minimize downtime, and improve overall operational efficiency.


                                  A structured OT taxonomy enables better data analytics by providing a clear
                Data Analytics
                                  framework for organizing and analyzing data. This leads to valuable insights that
                 & Insights
                                  can drive continuous improvement and innovation.


Asset Inventory Guidance for Owners and Operators                                                                                                                  TLP:CLEAR


    Steps to Develop an OT Asset Inventory and Taxonomy
    The authoring agencies recommend owners and operators complete the following steps to develop an OT
    asset inventory and taxonomy (see Figure 1 ):                          61T        61T


                                                             Identify Assets                          Create a                                                    Implement
               Define Scope and                                                                                                                   Manage and
                                                                   and                              Taxonomy to                                                    Life Cycle
                  Objectives                                                                                                                      Collect Data
                                                            Collect Attributes                    Categorize Assets                                              Management


                                                                                 Figure 1: Asset Inventory Steps

    1. Define Scope and Objectives .
         61T                                                         61T


         a.       Define governance over asset management . Identify the authority that requires an OT asset
                 61T                                                                               61T


                 inventory be created. Determine what offices or positions in the organization are responsible for
                 and/or benefit from establishing and maintaining the inventory.
         b.        Assign roles . Assign roles and responsibilities for data collection and validation.
                 61T                61T


         c.      Define the scope. Set the boundaries of the program (e.g., specific zones, facilities, systems, and
                 61T                                  61T


                 development timeline) and identify what constitutes an “asset” for the purposes of the inventory.
    2. Identify Assets and Collect Attributes.
         61T


         a.       Identify assets . Conduct a physical inspection and logical survey by gathering detailed digital and
                 61T                      61T


                 network-based information about system components. Compile a comprehensive list of OT assets
                 and network infrastructure dependencies. The scope of the asset inventory should consider assets
                 identified in documentation and physical inspection.
         b.       Collect asset attributes . These should be included in the inventory as fields that describe the
                 61T                                           61T


                 asset. Prioritize the collection of the following high priority attributes (see Appendix A: Asset                                        61T


                 Inventory Fields for information on the benefit of these attributes and other attributes that the
                                                61T


                 authoring agencies recommend collecting if your organization is resourced to collect them):
                   i. Active/supported communication                                                                       viii. Media Access Control (MAC) address
                      protocols                                                                                             ix. Manufacturer
                 ii. Asset criticality                                                                                      x. Model
                 iii. Asset number                                                                                          xi. Operating system (OS)
                 iv. Asset Role/Type                                                                                       xii. Physical location/address
                 v. Hostname                                                                                               xiii. Ports/services
                 vi. IP address                                                                                            xiv. User accounts
                vii. Logging

    3. Create a Taxonomy to Categorize Assets.
        61T


    There are five steps to build a taxonomy (see Figure 2 ). Note: See Appendix B: Taxonomy for Oil and Gas
                                                                                            61T          61T   61T   61T           61T


    Organizations , Appendix C: Taxonomy for Electricity Organizations , and Appendix D: Water and
                        61T   61T                                                                                            61T            61T


Asset Inventory Guidance for Owners and Operators                                                                                                                    TLP:CLEAR


    Wastewater for taxonomies CISA developed through working sessions for oil and gas organizations and
                           61T


    electricity organizations in the Energy Sector and for Water and Wastewater Sector organizations.

                                                               Categorize (Organize)
                                                                 Assets and their                    Organize Structure       Validate and                     Periodically Review
             Classify Assets
                                                                 Communications                      and Relationships         Visualize                           and Update
                                                                    Pathways

                                                                           Figure 2: How to Build an OT Taxonomy

        a.      Classify assets. Some common methodologies for classifying OT assets align to criticality or
               61T                                       61T


               function.
                     i.     Criticality-based classification :
                          61T                                                            61T


                          (1) Assets are classified based on their importance to the organization's operations, safety,
                              and mission.
                          (2) Critical assets are those whose failure or compromise would have the most significant
                              impact.
              ii.           Function-based classification :
                          61T                                                      61T


                          (1) Assets are grouped based on their roles or exposure within the OT environment, such as
                              control systems, communication devices, monitoring tools, engineering, maintenance, or
                              management functions.
                          (2) This approach helps in understanding dependencies and interconnections.
        b.      Categorize (organize) assets and their communications pathways.
               61T


               Note: There are multiple models and standards to organize assets, communications pathways, and
                                 61T


               others; this is at the discretion of the organization. The International Society of Automation
               (ISA)/International Electrotechnical Commission (IEC) 62443 series of standards—which CISA used
               to develop the taxonomies in Appendix B: Taxonomy for Oil and Gas Organizations , Appendix C:
                                                                             61T                                                                   61T   61T


               Taxonomy for Electricity Organizations , and Appendix D: Water and Wastewater —organizes assets
                                                                                               61T     61T                                   61T


               into Zones and Conduits: 6                            P5F


                     i. A Zone is a grouping of logical or physical assets (e.g., control assets, safety assets, assets in a
                                       61T   61T


                        demilitarized zone [DMZ]) that share common security requirements based on factors such as
                        criticality and consequence. For example, all machines that control a production line might be
                        in one Zone because they need the same level of protection. Zones help place focus on
                        securing similar assets, where current security capabilities can be compared against
                        established requirements.
              ii.         Conduits consist of the grouping of cyber assets dedicated exclusively to communications, and
                          61T                      61T


                          which share the same cybersecurity requirements. They ensure that only authorized data or
                          traffic can pass between Zones. For instance, a Conduit might connect a factory's control
                          system to its monitoring system, but with strict rules to prevent unauthorized access. OT


    6 Security for Industrial Automation and Control Systems – Part 3‑2: Security Risk Assessment for System Design.

    International Society of Automation, 2020.


Asset Inventory Guidance for Owners and Operators                                                           TLP:CLEAR


                      systems can be connected to several conduits simultaneously. To determine Conduits,
                      organizations should map communication pathways between zones incorporating data flow
                      analysis, protocol identification, and Layer2/Layer3 network details.
        c.     Organize structure and relationships.
             61T


                   i. Identify process dependencies (e.g., operational sequences or control flows).
             ii. Adopt consistent naming conventions for assets to ensure clarity and consistency across the
                 hierarchy.
             iii. Create detailed documentation to include naming convention methodology, structure, and
                  deviations.
             iv. Document roles and responsibilities of interaction with assets—operators, technicians, vendors,
                 integrators, etc. (ownership of functions like operations or maintenance, not access or
                 credential specific).
        d.     Validate and visualize.
             61T


                   i. Cross-check collected inventory for accuracy and completeness.
             ii. Create diagrams to represent asset categories (e.g., Zones and Conduits). See Figure 3 for an
                                                                                                      61T   61T


                 example diagram of an electricity organization taxonomy aligned to Zones and Conduits.


                               Figure 3: Example Distribution Environment Reference Architecture 7
                                                                                                P6F


    7 Provided by the National Renewable Energy Laboratory (NREL).


Asset Inventory Guidance for Owners and Operators                                                            TLP:CLEAR


              iii. Use tables or charts to show asset relationships and dependencies.
        e.      Periodically review and update.
              61T


                    i. Periodically review and update the taxonomy to reflect changes in technology and operations.
              ii. Gather feedback from stakeholders to ensure the taxonomy meets their needs and accurately
                  represents the OT environment.
    4. Manage and Collect Data.
        61T


        a.     Identify additional asset information sources. Identify sources of data for each asset (e.g.,
              61T                                                 61T


              integrator agreements, vendor manuals and handbooks, maintenance records, recorded
              operational data, and configuration specifications) that may enhance the inventory and conduct a
              cost-benefit analysis of including them.
        b.    Store data. Establish a centralized database or asset management system to store and manage
              61T             61T


              additional asset data, implementing security controls to ensure data protection and resilience
              against cyber threats.
    5. Implement Life Cycle Management.
        61T


        a.    Define life cycle stages . Define the stages of each asset’s life cycle (e.g., acquisition, deployment,
              61T                         61T


              commissioning, maintenance, and decommissioning).
        b.     Develop life cycle policies. Develop policies for managing assets throughout their life cycle,
              61T                               61T


              including maintenance schedules, replacement plans, and backup strategies. This includes
              following an organization’s change management process and requiring asset inventory updates for
              introduction or removal of devices into the system in all cases, even under emergency change
              authority.


    Post Inventory and Taxonomy Development Actions
    The following sections outline key actions OT owners and operators should take with their inventory.


    OT Cybersecurity and Risk Management
             Identify known vulnerabilities , available patches, updates, and hardening guidance for vendor
              61T                                           61T


              systems and applications.
             Cross-reference inventories with established vulnerability databases, such as CISA’s Known
              61T                                     61T


              Exploited Vulnerabilities (KEV) Catalog, which highlights actively exploited vulnerabilities, and
              MITRE’s Common Vulnerabilities and Exposures (CVE) database 8 , which provides detailed reports
                                                                                       P7F   P


              on identified security flaws.
              ○        Continuously explore security controls for known OT vulnerabilities in vendor systems and
                       applications that cannot be patched immediately or are end of life.


    8 “Common Vulnerabilities and Exposures (CVE).” cve.org. Accessed June 24, 2025. https://www.cve.org/.


Asset Inventory Guidance for Owners and Operators                                                                          TLP:CLEAR


             ○     Prioritize critical assets and systems and detail redundancy plans and the ability to operate
                   under compromise if vulnerabilities are targeted in critical assets and systems.
             ○     Implement real-time monitoring to detect emerging threats and vulnerabilities.
             ○     Use the KEV catalog as authoritative input to a vulnerability management prioritization
                   framework. Vulnerability management frameworks—such as the Stakeholder-Specific
                   Vulnerability Categorization (SSVC) model—consider a vulnerability’s exploitation status.
                   Organizations should also consider using automated vulnerability and patch management tools
                   that automatically incorporate and flag or prioritize KEV vulnerabilities.
             Prioritize threat factors by mapping potential attack patterns to known threat intelligence sources
             61T                          61T


             like MITRE ATT&CK Matrix for ICS 9 and MITRE’s Common Attack Pattern Enumeration and
                                                              P8F   P


             Classification (CAPEC): Industrial Control System Patterns. 10 Prioritize security efforts based on the
                                                                                    P9F   P


             most critical risks.
            Strengthen security posture by designing a security architecture that incorporates effective
             61T                                      61T


             controls, such as segmentation, access management, and monitoring.


    Maintenance and Reliability
            Review maintenance plans , considering vulnerability assessment findings and mitigations.
             61T                                61T


             Schedule mitigating actions or patching during maintenance windows—unless urgency drives an
             emergency change.
            Compare the costs of potential downtime or degraded services with the cost of replacing these
             61T                    61T


             vulnerable systems (if they are legacy) or deploying compensating controls.
             Implement more secure systems by using cyber-informed engineering 11 principles and secure by
             61T                                            61T                                    P10F   P


             design guidance to embed security in the procurement of new systems and engineering designs
             (See joint guide Secure by Demand: Priority Considerations for Operational Technology Owners and
             Operators when Selecting Digital Product). Leverage taxonomy and risk management processes to
             inform security decisions.
            Analyze OT spare parts inventory to determine whether the stockpile of spare OT components
             61T                                            61T


             sufficiently covers the critical assets identified in the inventory to ensure operational reliability.


    9 “ICS Matrix.” MITRE ATT&CK®. Accessed June 24, 2025. https://attack.mitre.org/matrices/ics/.

    10 “CAPEC VIEW: Industrial Control System (ICS) Patterns.” MITRE. Accessed June 27, 2025.
    https://capec.mitre.org/data/definitions/703.html.
    11 “Cyber-Informed Engineering,” Idaho National Laboratory (INL). Accessed June 24, 2025. https://inl.gov/national-security/cie/.


Asset Inventory Guidance for Owners and Operators                                                     TLP:CLEAR


    Performance Monitoring and Reporting
            Continuously monitor asset performance and status ; prioritize process variable monitoring focused
            61T                                                     61T


            on real-time indicators like temperature, pressure, or flow to detect performance issues or
            maintenance needs, and/or network and system diagnostics monitoring, which leverages
            continuous monitoring tools to analyze communication health, device connectivity, and process
            flow integrity.
           Develop reporting mechanisms to track asset performance, maintenance activities, and
            61T                                   61T


            compliance with policies.
           Identify asset inventory owners to oversee updates and validate asset classifications to ensure the
            61T                                  61T


            ongoing accuracy, maintenance, and reporting of the OT asset inventory.


    Training and Awareness
             Train staff in asset management practices, tools, and procedures.
            61T        61T


           Implement awareness programs to ensure all stakeholders understand the importance of asset
            61T                                         61T


            management.


    Continuous Improvement
            Implement a feedback loop to gather insights from asset management activities and identify areas
            61T                            61T


            for improvement.
           Use change management processes to accurately track OT asset modifications, additions, and
            61T                                               61T


            decommissioning.
           Conduct regular reviews of the inventory and audits of the asset management program to ensure it
            61T                      61T


            remains effective and aligned with organizational goals.


    Additional Resources
    For more information on asset management and OT cybersecurity, see the following resources:
           NIST’s Cybersecurity Framework
           CISA’s Principles of Operational Technology Cyber Security
           CISA’s Cybersecurity Performance Goals (CPGs)
           EPA’s Water Sector Cybersecurity Program Case Study: Small Wastewater System


    Questions and Feedback
    Stakeholders are encouraged to provide feedback via CISA’s anonymous product survey.


Asset Inventory Guidance for Owners and Operators                                                         TLP:CLEAR


    Contact Information
    U.S. organizations are encouraged to report suspicious or criminal activity related to information in this
    61T                       61T


    guide to:
             CISA via CISA’s 24/7 Operations Center at SOC@mail.cisa.dhs.gov or 1-844-Say-CISA (1-844-729-
              2472) or your local FBI field office. When available, please include the following information
              regarding the incident: date, time, and location of the incident; type of activity; number of people
              affected; type of equipment used for the activity; the name of the submitting company or
              organization; and a designated point of contact.
             For NSA cybersecurity guidance inquiries, contact CybersecurityReports@nsa.gov.
             Water and Wastewater Systems Sector organizations, contact the EPA Water Infrastructure and
              Cyber Resilience Division at watercyberta@epa.gov to voluntarily provide situational awareness.
     Australian organizations visit cyber.gov.au or call 1300 292 371 (1300 CYBER 1) to report cybersecurity
    61T                                         61T


    incidents and access alerts and advisories.
      Canadian organizations report incidents by emailing Cyber Centre at contact@cyber.gc.ca.
    61T                                   61T


    German organizations visit bsi.bund.de/EN/IT-Sicherheitsvorfall/it-sicherheitsvorfall_node.html to report
    61T                             61T


    cyber security incidents.
    Netherlands’ organizations visit ncsc.nl for advisories, and report incidents by emailing NCSC-NL at
    61T                                               61T


    cert@ncsc.nl.
      New Zealand organizations report cyber security incidents to incidents@ncsc.govt.nz or call 04 498 7654.
    61T                                                     61T


    Disclaimer
    This document does not address OT safety topics, such as risks to human life, health, property, or the
    environment. This document does not create policies, impose requirements, mandate actions, or override
    existing legal or regulatory obligations. All actions taken under this document are voluntary.
    The information in this report is being provided “as is” for informational purposes only. The authoring
    agencies do not endorse any commercial entity, product, company, or service, including any entities,
    products, or services linked within this document. Any reference to specific commercial entities, products,
    processes, or services by service mark, trademark, manufacturer, or otherwise, does not constitute or
    imply endorsement, recommendation, or favor by the authoring agencies.


    Version History
      August 13, 2025: Initial version.
    61T                 61T


Asset Inventory Guidance for Owners and Operators                                                                           TLP:CLEAR


    Appendix A: Asset Inventory Fields
    Successful asset management requires understanding what data to capture for each asset in an inventory.
    Table 1 shows recommended asset inventory fields and potential benefits of including them.
    61T           61T


    For a more detailed description of the attributes with respect to monitoring using CISA’s Malcolm and
    vulnerability management using the Common Security Advisory Framework (CSAF) 12 , see the following
                                                                                                     P11F   P


    repository 13 :     P12F   P


                        Table 1: Asset Inventory Fields, Attributes, and Recommendation on Priority of Requirement

              Asset Inventory Field
             0B


                                                                   Attribute Benefit
                                                                  1B


                                                                                                                        Priority
                                                                                                                       2B


                                             Useful for analyzing network traffic.

          Active/Supported                   Initially focus on assets that interact with devices outside
                                             the IT/OT perimeter or with supervisory control and data           High
          Communication Protocols
                                             acquisition (SCADA) devices over a wide area network,
                                             followed by assets that do not.

                                             Enables assets to be managed based on their operational
          Asset Criticality                                                                                     High
                                             role, safety impact, and/or exposure to risks.

                                             Unique identifier assigned to the asset by the
          Asset Number                                                                                          High
                                             organization.

                                             Useful for understanding context and function of the asset
                                             in the network.
                                             Common examples of asset type are:
                                                  Engineering workstation
          Asset Role/Type                                                                                       High
                                                  Programmable logic controller (PLC)
                                                  Historian
                                                  Network switch/router
                                                  Hypervisor host

                                             Potentially useful for understanding context and function
          Hostname                           of the asset in the network if included in host naming             High
                                             conventions.

          IP Address                         Useful in analyzing network traffic.                               High


    12 “Common Security Advisory Framework (CSAF),” Oasis, accessed August 8, 2025, https://www.csaf.io/.

    13 “DINA-community/String-Sysiphos/Attributes of Data Model,“ GitHub, last modified August 2, 2025, https://github.com/DINA-
    community/String-Sysiphos/blob/main/datamodel/datamodel_attributes.md.


Asset Inventory Guidance for Owners and Operators                                                                TLP:CLEAR


          Asset Inventory Field
         0B


                                                          Attribute Benefit
                                                         1B


                                                                                                             Priority
                                                                                                            2B


                                   Provides details about how logs from the asset are
      Logging                      collected to enable detection and investigation of                High
                                   potentially malicious activity.

                                   Useful for determining manufacturer, if not otherwise
      MAC address                  specified.                                                        High
                                   ( Note: Could only refer to network card manufacturer.)
                                    61T   61T


      Manufacturer                 Useful for determining known vulnerabilities.                     High

      Model                        Useful for determining known vulnerabilities.                     High

      Operating System             Useful for determining known vulnerabilities, if applicable.      High

      Physical Location/Address    Provides detail on where to find the asset.                       High

                                   Useful for verifying role and determining attack surface,
                                   but extremely time consuming to develop and maintain.
                                   Initially focus on assets that interact with devices outside
                                   the OT security perimeter or with SCADA devices over a
      Ports/Services               wide area network, followed by assets that do not.                High
                                   Note: If there is not an active cyber security control (e.g., a
                                   firewall) preventing communication outside the OT
                                   perimeter, then focus would apply to all assets for
                                   ports/services.

                                   Useful in knowing which user account is expected to be
      User Accounts                most active, or if the asset is expected to be accessed by        High
                                   many different users.

                                   Provides frequency for how often backups are performed
      Backup Frequency/Type        (e.g., daily, weekly, monthly) and method used (e.g., full,       Medium
                                   incremental, differential).

                                   Useful to know if there is a particular known-good image
      Baseline Image               that the OS installation was based on, aiding in post-            Medium
                                   incident recovery.

                                   Useful in understanding who owns or is responsible for the
      Department/Owner                                                                               Medium
                                   asset.


Asset Inventory Guidance for Owners and Operators                                                            TLP:CLEAR


          Asset Inventory Field
         0B


                                                          Attribute Benefit
                                                         1B


                                                                                                         Priority
                                                                                                        2B


                                   Useful in understanding where an asset originates (may
      Distributor                                                                                 Medium
                                   not be manufacturer).

      Firmware/Software Version    Useful for determining known vulnerabilities, if applicable.   Medium

      OS Version                   Useful for determining known vulnerabilities, if applicable.   Medium

      Physical or Virtual          Provides context on whether asset is physical or virtual.      Medium

      Virtual Local Area Network
                                   Offers visibility into the asset’s network structure.          Medium
      (VLAN)

      Antivirus (AV)/Endpoint      Provides details on the asset’s capability to protect itself
                                                                                                  Low
      Protection                   from malicious activities.

      Date of Manufacture          Useful in determining obsolescence.                            Low

                                   Provides context in what type of hypervisor is running the
      Hypervisor (if applicable)                                                                  Low
                                   virtual machine (VM).

                                   Useful when conducting user behavior analysis where
      Local Time Zone                                                                             Low
                                   timelines come into play.

      Location Within Hypervisor   Provides context on where the VM resides within the
                                                                                                  Low
      (if applicable)              hypervisor.

                                   Provides information about how well communications to
      Network Monitoring           the asset are monitored to detect potentially malicious        Low
                                   communications.


                                   Provides additional context about the asset, how it is
      Notes/Description                                                                           Low
                                   used, issues it has had, etc.


                                   Useful to limit attack surfaces and assess whether an
      Primary Communication        incident is local, remote, or network-wide (e.g., wired,
                                                                                                  Low
      Method                       wireless, cellular, microwave/radio frequency (RF),
                                   satellite), and corollary to communications protocols.

                                   Unique identifier; needed to verify some access to vendor
      Serial Number                                                                               Low
                                   patches/support.


Asset Inventory Guidance for Owners and Operators                                                            TLP:CLEAR


          Asset Inventory Field
         0B


                                                         Attribute Benefit
                                                        1B


                                                                                                         Priority
                                                                                                        2B


                                   Provides clarity on how an asset synchronizes its
                                   operations (e.g., Network Time Protocol (NTP), GPS,
      Time Source                  Atomic Clock, Local Clock) as disruption of an external        Low
                                   time source and associated drift could result in significant
                                   impacts.


  Asset Inventory Guidance for Owners and Operators                                                                  TLP:CLEAR


        Appendix B: Taxonomy for Oil and Gas Organizations
        CISA conducted a virtual exercise with working session participants from the Oil and Natural Gas Subsector
        to identify the necessary steps for organizations to develop their own OT taxonomy. Since this exercise was
        virtual, CISA did not perform actions that required direct knowledge of physical sites, component details or
        asset attributes, dependencies, or data flows.
        The authoring agencies encourage Oil and Natural Gas Subsector organizations to use this taxonomy as
        one example for developing their own taxonomies.


        Exercise Steps
             1. Identify Assets.
                61T


                a. Through a rapid data collection exercise, CISA generated a notional list of oil and natural gas
                   assets. Since CISA could not conduct a physical inspection, CISA started with identifying key OT
                   process areas with participants:
                            i. Safety systems
                            ii. Management/engineering
                           iii. Process control and monitoring
                           iv. Environmental systems
                            v. Communications systems
                           vi. Network equipment
                           vii. Cyber-physical security
                b. After identifying the key process areas, CISA identified the notional assets listed in Table 2 for
                                                                                                               61T         61T


                   each key process area (this list is not exhaustive and may not capture all relevant assets):

                      Table 2: Notional Oil and Natural Gas Subsector Organization Asset List by OT Process Area

                                              Process
                                                5B


                       Management/
                      4B


                                                                                                     Network
                                                                                                     8B


                                                                                                                       Cyber-Physical
                                                                                                                      9B


    Safety
   3B


                                             Control and    Environmental
                                                           6B


                                                                                Communications
                                                                               7B


                        Engineering                                                                 Equipment             Security
                                             Monitoring

                 Temporary
                                                                                                                      Identity and
Emergency        connected devices                                                                 Network
                                             SCADA         Stack monitoring   Wired                                   access
shut down        (i.e., laptops,                                                                   switches
                                                                                                                      management
                 removable media)

                                             Distributed
                 Integrated data                           Continuous                                                 Detection and
Fire and gas                                 control                          Microwave back
                 management                                environmental                           Firewalls          monitoring
systems                                      systems                          haul
                 systems                                   monitoring                                                 systems
                                             (DCS)


  Asset Inventory Guidance for Owners and Operators                                                                      TLP:CLEAR


                                               Process
                                                5B


                        Management/
                       4B


                                                                                                           Network
                                                                                                           8B


                                                                                                                           Cyber-Physical
                                                                                                                          9B


    Safety
   3B


                                              Control and      Environmental
                                                              6B


                                                                                  Communications
                                                                                 7B


                         Engineering                                                                      Equipment           Security
                                              Monitoring

                                                                                                         Infrastructur
Controllers/s
                                                                                                         e monitoring
afety             Remote access                                                 Industrial Internet of                    Antivirus
                                             PLC             Leak detection                              (uptime
instrumented      (jump-server)                                                 Things (IIoT) network                     /patching
                                                                                                         performance,
systems
                                                                                                         fault status)


                                             Advanced                                                    Wireless
Sequence of       Backup and                                                                                              Vulnerability
                                             process         Heat tracing       Cellular modems          access
events            recovery                                                                                                scanning
                                             control                                                     points


Electrical        Engineering                                Building
                                                                                Two-way radio            Media            Endpoint
safety/load       maintenance                Historian       management
                                                                                networks                 converters       detection
shed              network                                    systems (BMS)


                                             Third-Party
                                             packages
                                             (e.g.,
                  Virtualization/cont        compressor,     Power                                                        Physical
Dynamic
                  ainers/orchestrati         turbine         management         Fiber optic networks     Data diodes      access control
positioning
                  on                         controls,       systems                                                      systems
                                             burner,
                                             packaged
                                             boiler)


              2. Classify Assets.
                 61T


                 a. CISA created three criticality classifications based on security considerations:
                             i. High-criticality assets should have the most stringent security measures, such as network
                                segmentation and role-based access control.
                            ii. Medium-criticality assets should have robust monitoring and regular updates to ensure
                                reliability.
                            iii. Low-criticality assets should have basic security measures. They are included in the
                                 inventory for completeness.
                 b. CISA refined the key process areas previously identified ( Table 2 ) into functions.
                                                                                       61T      61T


Asset Inventory Guidance for Owners and Operators                                                                                                               TLP:CLEAR


          3. Categorize Assets.
                    61T


                    a. CISA grouped the functions into like categories (i.e., Zones. CISA grouped the Zones by
                       criticality). This resulted in the asset taxonomy shown in Table 3 through Table 5 .                       61T         61T


                                                                   Table 3: High-Criticality Assets

                Primary Production
              10B


                                                         Safety Systems
                                                       11B                                      12B


                                                                                                    Control Systems                       Power Systems
                                                                                                                                        13B


                    Systems

                                                Emergency shutdown
      Drilling rigs                                                                       DCS                               Backup generators
                                                systems (ESD)

                                                Fire and gas detection                    PLCs for critical                 Uninterruptible power
      Wellheads
                                                systems                                   processes                         supplies (UPS)

                                                Blowout preventers
      Subsea equipment
                                                (BOP)


                                                             Table 4: Medium-Criticality Assets

                                                                                                Communications
                                                                                              16B


          Processing Equipment
        14B


                                                   Monitoring Systems
                                                 15B


                                                                                                                              Networking Equipment
                                                                                                                            17B


                                                                                                   Systems

                                                Condition monitoring                                                        Switches and routers for
      Separators (oil, gas, water)              sensors (vibration,                       SCADA systems                     process control
                                                temperature, pressure)                                                      networks

                                                                                          Remote terminal units
      Compressors                               Data historians
                                                                                          (RTUs)

      Heat exchangers


                                                                   Table 5: Low-Criticality Assets

                            Auxiliary Systems
                          18B


                                                                               Non-Critical Monitoring
                                                                             19B


                                                                                                                        Peripheral Devices
                                                                                                                      20B


      Heating, ventilation, and air                                      Environmental monitoring (e.g.,
                                                                                                                Operator workstations
      conditioning (HVAC) systems                                        emissions tracking)

                                                                                                                Non-critical human-machine
      Lighting systems                                                   Non-essential data logging
                                                                                                                interfaces (HMI)


          4. Next Steps.
                    61T


                    a. CISA did not complete the Organizing Assets and Their Communications Pathways , Organize
                                                             61T                                                                                    61T   61T


                       Structure and Relationships , and Validate and Visualize steps because they require identified
                                                                   61T             61T                    61T


                       assets and knowledge of deployed communications pathways and process dependencies. By


Asset Inventory Guidance for Owners and Operators                                                     TLP:CLEAR


                completing these next steps in a real inventory, an Oil and Natural Gas Subsector organization
                would be able to create a taxonomy that illustrated asset zones, conduits, and categories, as
                well as asset relationships and dependencies. This would enable them to create a taxonomy
                that accurately represents their OT environment and aids with completion of the inventory.


Asset Inventory Guidance for Owners and Operators                                                          TLP:CLEAR


    Appendix C: Taxonomy for Electricity Organizations
    CISA conducted a virtual exercise with working session participants from electricity organizations in the
    Energy Sector to identify the necessary steps for organizations to develop their own OT taxonomy. Since
    this exercise was virtual, CISA did not perform actions that required direct knowledge of physical sites,
    component details or asset attributes, dependencies, or data flows.
    The authoring agencies encourage Energy Sector organizations to use this taxonomy as one example for
    developing their own taxonomies.


    Exercise Steps
        1. Identify Assets .
            61T                 61T


            a. Through a rapid data collection exercise, CISA generated a notional list of electricity
               organization assets. Since CISA could not conduct a physical inspection, CISA started with
               identifying key OT process areas with participants:
                   iv. DMZ
                   v. Communications systems
                   vi. Power generation
                  vii. Power transmission and distribution
                  viii. Physical access controls, electronic access control, or monitoring systems
                   ix. Energy management systems (EMS)
                   x. Distributed energy resource (DER) storage
                   xi. Energy
            b. After identifying the key process areas, CISA identified the notional assets listed in Table 6 for
                                                                                                     61T     61T


               each key process area (this list is not exhaustive and may not capture all relevant assets):


  Asset Inventory Guidance for Owners and Operators                                                             TLP:CLEAR


                          Table 6: Notional Electricity Organization Asset List by OT Process Area

                                                                    Physical
                                                                     25B


                                                                     Access
                                                                                      Energy
                                                                                      26B


                                                                    Controls,                          Distributed
                                                                                                     27B


                                                  Transmission
                                                24B


                                                                                     Manage-                           Energy
                                                                                                                       28B


                Communication
              22B


                                    Generatio
                                  23B


                                                                   Electronic                            Energy
     DMZ
   21B


                                                       and                             ment                           Resource
                     s                 n                             Access                            Resources
                                                   Distribution                      Systems                           Storage
                                                                   Control, or                           (DER)
                                                                                      (EMS)
                                                                   Monitoring
                                                                    Systems

                                                                                                                     Power
                                                                                                                     control
                                                                                   Condition         Communi-
                                                Protective        Badge                                              system (i.e.,
              Digital analog                                                       monitoring        cations to
Firewalls                         HMI           controls          readers/smart                                      battery
              converters (DAC)                                                     (i.e., digital    and from
                                                (relays)          keys                                               manage-
                                                                                   fault record)     inverters
                                                                                                                     ment
                                                                                                                     system)

                                                                                   Centralized
                                                                                   remedial
Application                                                                                          Hybrid
              Microwave           PLCs          HMIs              Cameras          action                            Monitoring
servers                                                                                              inverter
                                                                                   scheme
                                                                                   (CRAS)

                                                                                                     Power
                                                                                                     control
                                                                                   Fault
                                                                                                     systems
                                                                                   Location
Cyber                             Engineering                                                        (distributed
                                                Engineering       Role Based       Isolation                         Mainte-
monitoring    Satellite           work-                                                              energy
                                                workstations      Access           Service                           nance
tools                             stations                                                           resources
                                                                                   Restoration
                                                                                                     manage-
                                                                                   (FLISR)
                                                                                                     ment
                                                                                                     system)

                                  Local area
Remote                            network
                                                                  Motion           Front end         Biomass         Pump/
Access        Fiber               (dependent    RTUs/PLCs
                                                                  detectors        processor         generators      hydro
Servers                           on age of
                                  facility)

Intrusion
                                  Turbine                         Intrusion        Alarm and         Solar photo-
detection/    Routers/                                                                                               Thermal
                                  control       Smart meters      detection        event             voltaic (PV)
prevention    switchers                                                                                              system
                                  systems                         systems          notifications     systems
services


  Asset Inventory Guidance for Owners and Operators                                                                                    TLP:CLEAR


                                                                                Physical
                                                                                25B


                                                                                 Access
                                                                                                       Energy
                                                                                                        26B


                                                                                Controls,                                   Distributed
                                                                                                                          27B


                                                             Transmission
                                                           24B


                                                                                                      Manage-                               Energy
                                                                                                                                            28B


                      Communication
                    22B


                                              Generatio
                                            23B


                                                                               Electronic                                     Energy
     DMZ
   21B


                                                                  and                                   ment                               Resource
                           s                     n                               Access                                     Resources
                                                              Distribution                            Systems                               Storage
                                                                               Control, or                                    (DER)
                                                                                                       (EMS)
                                                                               Monitoring
                                                                                Systems

                                                           Power line
                                                                                                    Phasor
Data                                        Renewa-        carrier com-      Controlled                                                   Com-
                    Cellular modems                                                                 measure-              Fuel cells
historians                                  bles           munication        access points                                                pressed air
                                                                                                    ment units
                                                           systems


             2. Classify Assets .
                    61T               61T


                    a. CISA created three criticality classifications based on security considerations:
                           i. High-criticality assets should have the most stringent security measures, such as network
                              segmentation and role-based access control.
                          ii. Medium-criticality assets require robust monitoring and regular updates to ensure
                              reliability.
                          iii. Low-criticality assets can have basic security measures but should still be included in the
                               inventory for completeness.
                    b. CISA refined the key process areas and assets previously identified (Table 6) into functions.
             3. Categorize Assets.
                    61T


                    a. CISA grouped the functions into like categories (i.e., Zones. CISA then grouped the Zones by
                       criticality). This resulted in the asset taxonomy shown in Table 6 through Table 9 .
                                                                                              61T     61T           61T         61T


                                                          Table 7: High-Criticality Assets

                Primary Equipment
              29B


                                                     Protection Systems
                                                   30B


                                                                                        Control Systems
                                                                                      31B


                                                                                                                Power Supply Systems
                                                                                                              32B


                                                  Protection relays
                                                  (over/under current),
                                                  distance type
         Power transformers                                                  DCS                              Backup generators
                                                  (impedance, reactance),
                                                  differential (current,
                                                  voltage)

                                                  Fault detection and        PLCs managing critical           (UPS for critical
         Circuit breakers
                                                  isolation mechanisms       functions                        equipment

         Switchgear                               Voltage regulators         SCADA systems


Asset Inventory Guidance for Owners and Operators                                                                                               TLP:CLEAR


                Primary Equipment
              29B


                                                    Protection Systems
                                                  30B


                                                                                           Control Systems
                                                                                         31B


                                                                                                                                 Power Supply Systems
                                                                                                                               32B


      Busbars


                                                        Table 8: Medium-Criticality Assets

          Monitoring and Measurement
        33B


                                                                                                                           Environmental Control
                                                                                                                         35B


                                                                   Communications Systems
                                                                 34B


                    Devices                                                                                                      Systems


                                                                                                        Cooling systems for
      Current and voltage sensors                             RTUs
                                                                                                        transformers or control rooms

      Metering devices for energy and                                                                   Heating, ventilation, and air
                                                              Gateways
      power quality                                                                                     conditioning (HVAC)

      Data historians for operational                         Networking equipment (switches,
      insights                                                routers)


                                                              Table 9: Low-Criticality Assets

                                                                 37B


                                                                       Peripheral and Non-Critical
                      Facility Support Systems
                    36B


                                                                                                                     Non-Critical Monitoring
                                                                                                                   38B


                                                                                Devices

      Lighting systems for indoor and                          HMIs for secondary or non-
                                                                                                       Ambient temperature sensors
      outdoor facilities                                       urgent systems

      Building security systems (non-critical                  Operator workstations used for          Alarm systems for minor
      zones)                                                   administrative tasks                    operational thresholds

         4. Next Steps.   61T


                          a. CISA did not complete the Organizing Assets and Their Communications Pathways , and
                                                        61T                                                                               61T


                              Organize Structure and Relationships , and Validate and Visualize steps because they require
                                61T                                          61T   61T                       61T


                             identified assets and knowledge of deployed communications pathways and process
                             dependencies. By completing these next steps in a real inventory, an electricity organization
                             would be able to create a taxonomy that illustrated asset zones, conduits, and categories, as
                             well as asset relationships and dependencies. This would enable them to create a taxonomy
                             that accurately represents their OT environment and aids with completion of the inventory.


       Asset Inventory Guidance for Owners and Operators                                                                  TLP:CLEAR


           Appendix D: Water and Wastewater
           CISA conducted a virtual exercise with working session participants from Water and Wastewater Sector
           organizations to identify the necessary steps for organizations to develop their own OT taxonomy. Since this
           exercise was virtual, CISA did not perform actions that required direct knowledge of physical sites,
           component details or asset attributes, dependencies, or data flows.
           The authoring agencies encourage Water and Wastewater Sector organizations to use this taxonomy as
           one example for developing their own taxonomies.


           Exercise Steps
               1. Identify Assets.
                   61T


                   a. Through a rapid data collection exercise, CISA generated a notional list of water and
                      wastewater assets. Since CISA could not conduct a physical inspection, CISA started with
                      identifying key OT process areas with participants:
                            i. Collection
                            ii. Water Treatment
                           iii. Water Distribution
                           iv. Re-Use Water
                            v. Data Management – Expand into Enterprise Integration Support
                           vi. Wastewater Treatment
                           vii. Communications Infrastructure
                   b. After identifying the key process areas, CISA identified the notional assets listed in Table 10 for
                      each key process area (this list is not exhaustive and may not capture all relevant assets):

                                        Table 10: Water and Wastewater Function-Based OT Taxonomy

                                                                            Data Management -
                                                                            43B


                            Water
                             40B


                                                                  Re-Use
                                                                42B


                                                                                Expand into            Wastewater
                                                                                                     44B


                                                                                                                      Communications
                                                                                                                    45B


   Collection
 39B


                                               Distribution
                                             41B


                          Treatment                               Water    Enterprise Integration      Treatment       Infrastructure
                                                                                  Support


Sewer                    Quality (pH,
                                         Pressure monitoring    Pump       Visualize and reporting   Pump
metering                 monitoring                                                                                 Fiber optic
                                         sensors                stations   tools                     stations
vaults                   systems)


                         Process                                Pressure
Sewage                                   Remote valve                      Business intelligence     Biological     Industrial
                         control                                reducing
pump station                             systems                           analytics                 treatment      Ethernet
                         (PLCs/RTUs)                            vaults


       Asset Inventory Guidance for Owners and Operators                                                                  TLP:CLEAR


                                                                            Data Management -
                                                                            43B


                            Water
                            40B


                                                                  Re-Use
                                                                42B


                                                                                Expand into           Wastewater
                                                                                                    44B


                                                                                                                      Communications
                                                                                                                    45B


   Collection
 39B


                                               Distribution
                                             41B


                          Treatment                               Water    Enterprise Integration     Treatment        Infrastructure
                                                                                  Support


Measurement              Chemical        Backup power                                               Solids          Industrial
                                                                Quality    Compliance
(flow meters)            dosing          management                                                 handling        wireless


Tank level                                                                                          Advanced
                         Environmental   Meters/telemetry       Metering   Databases/data lakes                     Cellular
sensor                                                                                              treatment


                                                                           Cybersecurity            Primary         Licensed and
Quality                  Temperature                            Aeration
                                         IOT sensors                       measures for data        settling        unlicensed radio
sensor                   transducer                             tanks
                                                                           protection in motion     tanks           networks


                                                                Treated
                                                                           Data
                         Nutrient                               water                               Sludge
Pressure                                 Pressure reducing                 communication/polling                    Microwave
                         removal                                storage                             dewatering
transducer                               valves                            software (OPC UA,                        backhaul
                         system                                 tank                                systems
                                                                           MQTT, Modbus)
                                                                levels


               2. Classify Assets.
                   61T


                   a. CISA created three criticality classifications based on security considerations:
                            i. High-criticality assets should have the most stringent security measures, such as network
                               segmentation and role-based access control.
                            ii. Medium-criticality assets require robust monitoring and regular updates to ensure
                                reliability.
                           iii. Low-criticality assets can have basic security measures but should still be included in the
                                inventory for completeness.


Asset Inventory Guidance for Owners and Operators                                                                                                  TLP:CLEAR


                      b. CISA refined the key process areas and assets previously identified ( Table 6) into functions.
                                                                                                               61T     61T


              3. Categorize Assets.
                      61T


                      a. CISA grouped the functions into like categories (i.e., Zones. CISA then grouped the Zones by
                         criticality). This resulted in the asset taxonomy shown in Table 11 through Table 13 .
                                                                                                 61T     61T            61T                  61T


                                                           Table 11: High-Criticality Assets

       Primary
        46B


                                Secondary
                              47B


                                                    Safety and
                                                     48B


                                                                                                                                     Power
                                                                                                                                       50B


      Treatment                 Treatment                                                    Control Systems
                                                                                           49B


                                              Environmental Systems                                                                 Systems
       Systems                   Systems

      Pumps (e.g.,
      intake,
                             Aeration        Emergency shutdown                                                                  Backup
      discharge,                                                                     SCADA systems
                             systems         systems                                                                             generators
      high-
      pressure)

      Screens,
      clarifiers,            Biological      Chemical dosing systems
      and grit               treatment       for pH control or                       DCS for core processes                      UPS
      removal                reactors        disinfection
      systems

                                                                                     OT communications
                                             Spill containment systems
                                                                                     infrastructure


                                                     Table 12: Medium-Criticality Assets

                  Water Quality
                51B


                                                 Communications
                                               52B                               Networking Equipment
                                                                               53B


                                                                                                                       54B


                                                                                                                             Auxiliary Systems
                   Monitoring                       Systems

      Online analyzers for                                                                                           Sludge management
      turbidity, chlorine, or               RTUs                             Network switches                        equipment (e.g.,
      dissolved oxygen                                                                                               pumps, centrifuges)

                                                                                                                     Non-essential
                                                                             Firewalls for process                   pumping systems
      Sampling stations                     PLCs
                                                                             control systems                         (e.g., irrigation or
                                                                                                                     utility water)


Asset Inventory Guidance for Owners and Operators                                                                                    TLP:CLEAR


                                                      Table 13: Low-Criticality Assets

               Facility Support Systems
             55B


                                                                          Peripheral Devices
                                                                        56B


                                                                                                           Non-Critical Monitoring
                                                                                                         57B


                                                                                                     Sensors for ambient
      HVAC                                                   HMIs for non-critical processes         temperature, facility water
                                                                                                     usage, or general alarms

      Lighting systems for buildings                         Operator workstations


        4. Next Steps.
                   61T


                   a. CISA did not complete the Organizing Assets and Their Communications Pathways , Organize
                                                61T                                                                      61T   61T


                      Structure and Relationships , and Validate and Visualize steps because they require identified
                                                       61T        61T                          61T


                      assets and knowledge of deployed communications pathways and process dependencies. (See
                      Figure 3 for an example diagram). By completing these next steps in a real inventory, a Water
                         61T   61T


                      and Wastewater Sector organization would be able to create a taxonomy that illustrated asset
                      zones, conduits, and categories, as well as asset relationships and dependencies. This would
                      enable them to create a taxonomy that accurately represents their OT environment and aids
                      with completion of the inventory.


Asset Inventory Guidance for Owners and Operators                                                     TLP:CLEAR


    References
    CVE.org. “Common Vulnerabilities and Exposures (CVE).” Accessed June 24, 2025. https://www.cve.org/.
    GitHub. “DINA-community/String-Sysiphos/Attributes of Data Model.” Last modified August 2, 2025.
           https://github.com/DINA-community/String-
           Sysiphos/blob/main/datamodel/datamodel_attributes.md.
    Idaho National Laboratory. “Cyber-Informed Engineering.” Accessed June 24, 2025.
           https://inl.gov/national-security/cie/.
    International Society of Automation. Security for Industrial Automation and Control Systems – Part 3‑2:
            Security Risk Assessment for System Design, 2020.
    MITRE. “CAPEC VIEW: Industrial Control System (ICS) Patterns.” Accessed June 27, 2025.
           https://capec.mitre.org/data/definitions/703.html.
    MITRE ATT&CK. “ICS Matrix.” Accessed June 24, 2025. https://attack.mitre.org/matrices/ics/.
    Oasis. “Common Security Advisory Framework (CSAF).” Accessed August 8, 2025. https://www.csaf.io/.
