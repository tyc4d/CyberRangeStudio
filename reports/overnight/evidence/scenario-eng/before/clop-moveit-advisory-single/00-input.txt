# CL0P and MOVEit Transfer: public advisory summary

**Source:** FBI and CISA, Joint Cybersecurity Advisory AA23-158A, issued 2023-06-07. [Official advisory PDF](https://www.cisa.gov/sites/default/files/2023-06/aa23-158a-stopransomware-cl0p-ransomware-gang-exploits-moveit-vulnerability.pdf). This fixture paraphrases the advisory; paragraph locators below refer to this summary, and the page references identify the supporting parts of the advisory.

The advisory reports that the CL0P group exploited CVE-2023-34362 in Progress MOVEit Transfer during May 2023. The affected software is identified as a managed file-transfer application. (Advisory pages 1 and 4: summary and vulnerability details.)

The advisory describes SQL injection against internet-facing MOVEit Transfer web applications, followed by installation of the LEMURLOOT web shell. It says the shell was used to retrieve information from the system and its underlying database. (Advisory page 4: vulnerability details.)

The advisory lists affected MOVEit Transfer release lines, but does not identify the installed release, hostname, operating system, or network placement of a particular victim. Those target details remain unknown for a Scenario IR built from this source. (Advisory page 4: affected versions and exploitation summary.)
