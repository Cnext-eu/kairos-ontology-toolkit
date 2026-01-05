# Security & Compliance

**Implementation Note:** This document has been updated to reflect the **Kairos Ontology Toolkit** as implemented - a CLI tool that generates artifacts locally. Security focuses on source code protection and user-configured deployment security.

## Overview
The Kairos Ontology Toolkit is a **build-time CLI tool** with no runtime data storage, servers, or user-facing services. Its security model focuses on:
1. **Source Code Protection:** Securing the ontology repository (✅ user implements)
2. **Artifact Integrity:** Ensuring generated artifacts are valid (✅ toolkit validates)
3. **Access Control:** Restricting who can modify ontologies (📋 user implements via Git)
4. **Audit & Compliance:** Maintaining traceability (✅ Git provides, 📋 user configures logging)

**Toolkit Security Scope:**
- ✅ Validates ontology syntax and SHACL constraints (prevents malformed artifacts)
- ✅ Generates artifacts locally (no network calls, no cloud dependencies)
- ✅ Open-source code (auditable by users)
- 📋 Authentication, authorization, deployment security: **user responsibility**
- 📋 CI/CD integration, artifact publishing: **user configures**

## Authentication Model

**Implementation Status:** 📋 USER CONFIGURES - Toolkit is a CLI tool with no authentication; users implement Git/CI/CD security

### Git Repository Authentication (Example - User Implements)
**Mechanism:** GitHub-native authentication (SSH keys, Personal Access Tokens, or OAuth Apps)

**Toolkit Role:** None - toolkit runs locally, reads .ttl files, writes to output/ directory  
**User Implements:** Git authentication, branch protection, access control

**Roles (Example):**
- **Repository Admins:** Full access, can modify branch protection rules
- **Write Access (Domain Experts, Core Developers):** Can create branches, commit, and open PRs
- **Read Access (All Developers):** Can clone, read, and fork repository

**Configuration Example:**
```yaml
# .github/settings.yml (Branch Protection) - USER CONFIGURES
branches:
  main:
    protection:
      required_pull_request_reviews:
        required_approving_review_count: 2
      required_status_checks:
        strict: true
        contexts:
          - validate  # User's CI/CD validation step
      enforce_admins: true
      restrictions:
        users: []
        teams: ["ontology-admins"]
```

**Token Expiry (User Responsibility):**
- Personal Access Tokens (PATs): 90-day rotation policy
- SSH keys: Annual review and rotation

### CI/CD Pipeline Authentication (Example - User Implements)
**Mechanism:** User configures (GitHub Actions, Azure DevOps, Jenkins, etc.)

**Toolkit Role:** None - toolkit CLI runs in user's CI/CD environment  
**User Implements:** CI/CD authentication, secret management, artifact publishing

**Example: GitHub Actions with Azure Blob Upload**
- **Type:** Azure Managed Identity or Service Principal with SAS token
- **Scope:** Write access to artifact storage (user's choice of storage)
- **Rotation:** SAS tokens regenerated per user's security policy
- **Storage:** GitHub Secrets (encrypted at rest)

**Configuration Example:**
```yaml
# GitHub Actions workflow - USER CONFIGURES
- name: Run Kairos Toolkit
  run: |
    pip install kairos-ontology
    kairos-ontology validate domains/
    kairos-ontology project domains/ --target all

- name: Upload Artifacts (User Implements)
  env:
    AZURE_STORAGE_CONNECTION_STRING: ${{ secrets.AZURE_STORAGE_CONNECTION }}
  run: |
    az storage blob upload-batch \
      --destination ontology-artifacts \
      --source output/ \
      --auth-mode key
```

## Authorization Model (RBAC)

**Implementation Status:** 📋 USER CONFIGURES - Toolkit has no authorization system; users implement via Git/CI/CD

### GitHub Repository Roles (Example - User Implements)

| Role | Permissions | Assigned To |
|------|-------------|-------------|
| **Admin** | Branch protection, settings, secrets management | Platform Architects (2-3 users) |
| **Maintain** | Manage issues, PRs, releases (no force push) | Ontology Team Lead |
| **Write** | Create branches, commit, open PRs | Domain Experts, Data Engineers |
| **Read** | Clone, read, fork | All developers |

**Toolkit Access:** Anyone with read access can run toolkit locally (no server-side authorization)

### CI/CD Pipeline Permissions (Example - User Implements)

| Action | Required Permission | Enforcement |
|--------|---------------------|-------------|
| Run toolkit validation | Ability to execute CLI | User's environment |
| Run toolkit projection | Ability to execute CLI | User's environment |
| Merge to main | 2 approvals + passing checks | Branch protection rules (user configures) |
| Publish artifacts | Storage access credentials | User's secret management |
| Create Git tags | Write access | User's CI/CD automation |

### Artifact Storage Access (Example - User Implements)

| Role | Permissions | Assigned To |
|------|-------------|-------------|
| **Publisher** | Write to storage | CI/CD automation (user configures) |
| **Consumer** | Read from storage | Runtime systems (user configures) |

**Example Azure Blob Access Policy:**
```json
{
  "publicAccess": "blob",
  "defaultEncryptionScope": "$account-encryption-key",
  "permissions": {
    "publisher": ["write", "delete"],
    "consumer": ["read", "list"]
  }
}
```

---

## Encryption

### Data in Transit
**Protocol:** TLS 1.3 for all network communications

| Connection | Encryption | Verification |
|------------|------------|--------------|
| Git clone/push (HTTPS) | TLS 1.3 | GitHub-managed certificates |
| Git clone/push (SSH) | SSH 2.0 with RSA 4096 or Ed25519 keys | Public key authentication |
| Azure Blob upload | HTTPS (TLS 1.3) | Azure-managed certificates |
| Artifact download | HTTPS (TLS 1.3) | Azure-managed certificates |

### Data at Rest
**Ontology Files in Git Repository:**
- **Encryption:** Not encrypted at rest (files are not sensitive; they define metadata, not data instances)
- **Rationale:** Ontology files contain class/property definitions, not PII or secrets
- **Policy:** Strict prohibition on committing PII, credentials, or sensitive data

**Artifacts in Azure Blob Storage:**
- **Encryption:** Azure Storage Service Encryption (SSE) with Microsoft-managed keys (AES-256)
- **Key Management:** Automatic key rotation by Azure (no manual intervention required)
- **Configuration:**
```bash
# Verify encryption is enabled (default for Azure Blob)
az storage account show --name <account> --query encryption
```

**GitHub Secrets (CI/CD):**
- **Encryption:** GitHub-managed encryption at rest
- **Access:** Only accessible to workflows with explicit permissions
- **Audit:** All secret access logged in GitHub audit log

## Audit Logging

**Implementation Status:**
- ✅ Toolkit: No logging infrastructure (CLI tool)
- ✅ Git: Provides commit history (primary audit trail)
- 📋 User Implements: CI/CD logs, storage access logs

### Git Commit History (Primary Audit Trail)
**Purpose:** Track all ontology changes (who, what, when, why)

**Logged Information:**
- **Author:** Git username and email
- **Timestamp:** Commit date/time
- **Changes:** Diff of modified .ttl/.shacl files
- **Message:** Commit message (required to explain "why")

**Retention:** Permanent (Git history is immutable)  
**Toolkit Role:** None - toolkit reads ontology files, Git tracks changes

**Example:**
```bash
git log --oneline --graph --all
# Output:
# a1b2c3d (HEAD -> main) feat: Add Customer class with email validation
# d4e5f6g docs: Update SKOS mappings for logistics domain
```

### CI/CD Pipeline Logs (User Implements)
**Purpose:** Track validation, projection, and publishing activities

**Toolkit Output:**
- Validation results (exit codes: 0 = success, non-zero = failure)
- Projection execution (stdout/stderr messages)
- Artifact generation confirmation

**User Implements:** CI/CD logging infrastructure

**Logged Information (Example):**
- Workflow trigger (PR, merge)
- Toolkit command execution (`kairos-ontology validate`, `project`)
- Artifact upload success/failure
- Execution time and resource usage

**Retention:** Per user's CI/CD platform (e.g., GitHub Actions 90 days default)

**Configuration Example:**
```yaml
# Enable detailed logging - USER CONFIGURES
- name: Run Toolkit Validation
  run: kairos-ontology validate domains/ --verbose 2>&1 | tee validation.log
  
- name: Upload Validation Log
  uses: actions/upload-artifact@v3
  with:
    name: validation-log
    path: validation.log
```

### Cloud Storage Access Logs (User Implements)
**Purpose:** Track artifact uploads and downloads (if user publishes to cloud)

**Toolkit Role:** None - toolkit generates to local output/ directory  
**User Implements:** Storage logging (Azure, AWS, GCS, etc.)

**Example: Azure Blob Storage**
```bash
# Enable Storage Analytics logging - USER CONFIGURES
az storage logging update \
  --account-name <account> \
  --log rwd \
  --retention 90 \
  --services b
```

### Access Review Logs (User Implements)
**Purpose:** Quarterly review of repository access

**Process (User Implements):**
1. Export GitHub organization members with repository access
2. Review against authorized personnel list
3. Revoke access for departed employees
4. Document review in compliance folder

**Retention:** 7 years (for compliance audits)

## Threat Model

**Toolkit Security:** CLI tool with no server components, minimal attack surface

### Threat: Unauthorized Ontology Modification
**Likelihood:** Medium  
**Impact:** High (corrupted semantics could propagate to all runtime systems)

**Toolkit Mitigations:**
- ✅ Validation pipeline prevents invalid ontologies from generating artifacts
- ✅ Open-source code (community can audit for backdoors)

**User Mitigations (Recommended):**
- 📋 Branch protection rules (2 required approvals)
- 📋 Git commit history provides rollback capability
- 📋 Quarterly access reviews

**Residual Risk:** Low (with user controls)

### Threat: Compromised CI/CD Pipeline
**Likelihood:** Low  
**Impact:** High (malicious artifacts could be published)

**Toolkit Mitigations:**
- ✅ No secrets/credentials required by toolkit
- ✅ Reads from local filesystem only (no network access)
- ✅ Open-source code (auditable)

**User Mitigations (Recommended):**
- 📋 CI/CD runs in isolated environments (ephemeral containers)
- 📋 Secrets stored in platform secrets (GitHub Secrets, Azure Key Vault, etc.)
- 📋 Service principals have minimal permissions (write to storage only)
- 📋 Dependency scanning (Dependabot, Snyk, etc.)

**Residual Risk:** Low (with user controls)

### Threat: Accidental PII Commit
**Likelihood:** Medium  
**Impact:** High (GDPR violation, regulatory fines)

**Toolkit Mitigations:**
- ✅ Toolkit processes ontology files (metadata), not data instances
- ✅ Validation errors prevent malformed ontologies (partial protection)

**User Mitigations (Recommended):**
- 📋 Automated scanning via Gitleaks (detects secrets, emails, patterns)
- 📋 Policy documentation: "No PII in ontology files"
- 📋 Pre-commit hooks (optional) to warn on suspicious patterns
- 📋 Git history rewrite procedure documented for accidental commits

**Residual Risk:** Low (with scanning)

**Pre-commit Hook Example:**
```yaml
# .pre-commit-config.yaml - USER CONFIGURES
repos:
  - repo: https://github.com/gitleaks/gitleaks
    rev: v8.18.0
    hooks:
      - id: gitleaks
```

### Threat: Artifact Tampering
**Likelihood:** Low  
**Impact:** Medium (runtime systems consume incorrect schemas)

**Toolkit Mitigations:**
- ✅ Deterministic generation (same input = same output)
- ✅ Embedded metadata (ontology URI in artifacts for traceability)

**User Mitigations (Recommended):**
- 📋 Immutable storage (Azure Blob versioning, S3 versioning)
- 📋 Checksums in deployment scripts
- 📋 HTTPS-only downloads (no HTTP fallback)
- 📋 Artifact versioning via Git tags

**Residual Risk:** Very Low

---

### Threat: Denial of Service (CI/CD)
**Likelihood:** Low  
**Impact:** Medium (delayed artifact publishing, no runtime impact)

**Toolkit Mitigations:**
- ✅ Efficient processing (minimal resource usage)
- ✅ No external network calls (can't be used for DDoS amplification)

**User Mitigations (Recommended):**
- 📋 CI/CD rate limiting (platform-specific)
- 📋 Workflow timeout limits
- 📋 Manual approval required for external PRs

**Residual Risk:** Low

## Compliance Requirements

**Toolkit Scope:** CLI tool with minimal compliance obligations  
**User Responsibility:** Compliance for Git repositories, CI/CD, artifact storage

### GDPR (General Data Protection Regulation)
**Applicability:** Limited (ontology defines metadata, not personal data)

**Toolkit:**
- ✅ Processes ontology files (no personal data)
- ✅ No data collection, no telemetry, no user tracking

**User Implements:**
- 📋 **Article 30 (Record of Processing):** Git commit history serves as processing record
- 📋 **Article 32 (Security):** Encryption in transit (TLS 1.3), access controls (RBAC)
- 📋 **Article 33 (Breach Notification):** 72-hour notification procedure (see Incident Response)

**Non-Applicable:**
- Right to access (no personal data in ontology)
- Right to deletion (no personal data in ontology)
- Consent management (no personal data processing)

**Policy Enforcement (User Implements):**
- Automated scanning prevents PII commits
- Annual GDPR compliance review

---

### ISO 27001 (Information Security Management)
**Applicability:** Organizational security standard (user implements)

**Toolkit:** Open-source, auditable code  
**User Implements:** All controls below

| Control | Implementation | Evidence |
|---------|----------------|----------|
| **A.9.2 (User Access Management)** | Git RBAC, quarterly access reviews | Access review logs |
| **A.10.1 (Cryptographic Controls)** | TLS 1.3, cloud storage encryption | Encryption settings |
| **A.12.3 (Backup)** | Git distributed copies, storage versioning | Backup verification logs |
| **A.12.4 (Logging & Monitoring)** | Git history, CI/CD logs, storage access logs | Log retention policies |
| **A.14.2 (Security in Development)** | Toolkit validation, dependency scanning | CI/CD test reports |
| **A.16.1 (Incident Management)** | Documented incident response plan | Incident response runbook |

---

### SOC 2 Type II (Service Organization Control)
**Applicability:** Partial (if ontology management offered as a service to external customers)

**Toolkit:** Not applicable (no SaaS offering)  
**User Implements:** If offering ontology management as a service

| Criterion | Implementation | Verification |
|-----------|----------------|--------------|
| **Security (CC6.1)** | Access controls, encryption, logging | Quarterly audits |
| **Availability (A1.1)** | Git platform SLA (e.g., GitHub 99.95%) | Uptime monitoring |
| **Processing Integrity (PI1.1)** | Toolkit validation, SHACL constraints | Validation reports |
| **Confidentiality (C1.1)** | TLS 1.3, storage encryption | Encryption audits |

**Note:** SOC 2 audit required only if ontology management is offered as SaaS/multi-tenant service

## Data Retention & Privacy

**Toolkit:** No data retention (processes files, generates output)  
**User Implements:** Retention policies for Git, CI/CD, artifact storage

### Retention Policies (User Configures)

| Data Type | Retention Period | Rationale | Deletion Method |
|-----------|------------------|-----------|----------------|
| **Git Commit History** | Permanent | Audit trail, rollback capability | N/A (immutable) |
| **CI/CD Logs** | 90 days (default) | Troubleshooting, recent audit | Platform automatic deletion |
| **Storage Access Logs** | 90 days (configurable) | Security monitoring | Cloud provider automatic deletion |
| **Artifacts** | Permanent (versioned) | Runtime systems depend on specific versions | Manual deletion of deprecated versions |
| **Access Review Logs** | 7 years | Compliance audits (SOC 2, ISO 27001) | Manual archival after 7 years |

### Privacy by Design
**Principle:** Minimize data collection, avoid PII

**Toolkit Implementation:**
- ✅ Processes ontology files (metadata only, no data instances)
- ✅ No telemetry, no user tracking, no data collection
- ✅ Generates artifacts to local filesystem only

**User Responsibility:**
- Ontology files define **classes and properties** (metadata), not **instances** (data)
- No user-generated content stored in repository
- CI/CD logs contain no PII (only system events)
- Artifact metadata includes ontology URI, no personal identifiers

**Example of Prohibited Content:**
```turtle
# ❌ PROHIBITED: Actual customer data
:Customer001 a :Customer ;
    :name "John Doe" ;
    :email "john.doe@example.com" .

# ✅ ALLOWED: Class definition
:Customer a owl:Class ;
    rdfs:label "Customer" ;
    rdfs:comment "An individual or organization that purchases products or services." .
```

## Incident Response Plan

**Toolkit:** No incident response needed (local CLI tool)  
**User Implements:** Incident response for Git, CI/CD, artifact storage

### Procedure: Compromised CI/CD Pipeline (User Implements)
**Detection:** Unusual artifact uploads, failed validation, suspicious Git commits

**Response Steps:**
1. **Immediate:** Revoke storage credentials, disable CI/CD workflows
2. **Investigation:** Review CI/CD logs, identify affected workflows
3. **Containment:** Delete suspicious artifacts from storage
4. **Recovery:** Regenerate artifacts from known-good commit using toolkit, rotate secrets
5. **Notification:** Inform security team within 1 hour, stakeholders within 24 hours

**Post-Incident:**
- Root cause analysis documented
- Update threat model and mitigations
- Review access controls

---

### Procedure: Accidental PII Commit (User Implements)
**Detection:** Gitleaks scan failure, manual report

**Response Steps:**
1. **Immediate:** Do NOT merge PR, halt pipeline
2. **Investigation:** Identify PII in commit diff
3. **Remediation (if not merged):** Remove PII, amend commit, force push
4. **Remediation (if merged to main):** Use BFG Repo-Cleaner or `git filter-repo` to rewrite history
5. **Notification:** GDPR breach notification within 72 hours if PII was exposed publicly

**Post-Incident:**
- Strengthen pre-commit hooks
- Additional training for team on PII policies

---

### Procedure: Artifact Tampering Detected (User Implements)
**Detection:** Unexpected artifact changes, integrity check failure

**Response Steps:**
1. **Immediate:** Quarantine affected artifact version, alert consumers
2. **Investigation:** Compare artifact with Git commit source
3. **Recovery:** Regenerate artifact from source commit using toolkit, re-publish
4. **Notification:** Inform runtime system owners within 1 hour

**Post-Incident:**
- Enable immutable storage (Azure Blob, S3 versioning)
- Review service principal permissions

---

## Security Best Practices

**Toolkit:** Minimal security surface (local CLI, no network)  
**User Implements:** Git, CI/CD, artifact storage security

### For Domain Experts (Ontology Authors)
✅ **DO:**
- Use strong, unique passwords for Git accounts
- Enable 2FA (two-factor authentication) on Git platform
- Write descriptive commit messages explaining changes
- Run toolkit validation locally before committing (`kairos-ontology validate`)
- Review validation errors before requesting PR approval

❌ **DON'T:**
- Commit actual data instances (only class/property definitions)
- Share Personal Access Tokens (PATs) with others
- Bypass validation pipeline or branch protection rules
- Include credentials, API keys, or PII in ontology files

### For Platform Engineers (CI/CD Maintainers)
✅ **DO:**
- Install toolkit in CI/CD environment (`pip install kairos-ontology`)
- Rotate storage credentials every 90 days (if publishing to cloud)
- Review platform secrets quarterly
- Monitor CI/CD logs for anomalies
- Keep dependencies up to date (Dependabot, Snyk, etc.)

❌ **DON'T:**
- Hardcode secrets in workflow YAML files
- Grant overly permissive cloud storage permissions
- Disable branch protection rules
- Skip toolkit validation steps in CI/CD

### For Consumers (Runtime Systems)
✅ **DO:**
- Pin artifact versions explicitly (e.g., use Git tags or versioned paths)
- Verify artifact integrity (Git commit hash in metadata)
- Test artifacts in staging environment before production
- Use toolkit locally for development/testing

❌ **DON'T:**
- Use "latest" version alias (no version pinning)
- Skip integrity verification
- Apply artifacts directly to production without testing

---

## Security Monitoring & Alerts

**Toolkit:** No monitoring infrastructure (CLI tool)  
**User Implements:** Monitoring for Git, CI/CD, artifact storage

### Automated Alerts (User Configures)

| Event | Alert Mechanism | Recipient | SLA |
|-------|----------------|-----------|-----|
| **Toolkit Validation Failure** | CI/CD status check | PR author | Immediate |
| **Secret Exposure Detected** | Gitleaks scan failure | Security team | Immediate |
| **Failed Artifact Upload** | CI/CD job failure notification | Platform team | 15 minutes |
| **Unusual Storage Access** | Cloud monitoring alert | Security team | 1 hour |
| **Dependency Vulnerability** | Dependabot/Snyk alert | Platform team | 24 hours |

### Manual Reviews (User Implements)

| Activity | Frequency | Responsible Team | Output |
|----------|-----------|------------------|--------|
| **Access Control Review** | Quarterly | Platform Architects | Access audit report |
| **Security Threat Model Update** | Annually | Security Team | Updated threat model |
| **Compliance Checklist** | Annually | Compliance Officer | ISO 27001/SOC 2 attestation |
| **Secret Rotation** | Every 90 days | Platform Engineers | Rotation log |

---

## Disaster Recovery

**Toolkit:** No disaster recovery needed (stateless CLI)  
**User Implements:** Backup/recovery for Git, artifacts

### Backup Strategy (User Configures)

| Asset | Backup Method | Frequency | Retention | Recovery Time Objective (RTO) |
|-------|---------------|-----------|-----------|-------------------------------|
| **Git Repository** | Git distributed architecture | Continuous | Infinite | < 1 hour (clone from platform) |
| **Artifacts** | Cloud storage versioning | Continuous | Infinite | < 4 hours (cloud failover) |
| **CI/CD Configuration** | Git-tracked workflow files | Continuous | Infinite | < 1 hour (restore from Git) |
| **Toolkit Installation** | PyPI package | On-demand | N/A | < 5 minutes (`pip install`) |

### Recovery Procedures (User Implements)

**Scenario 1: Git Repository Unavailable**
1. Wait for Git platform status confirmation (e.g., GitHub 99.95% SLA)
2. If prolonged: Clone from developer local copies
3. Migrate to alternative Git platform (1-2 day effort)

**Scenario 2: Cloud Storage Unavailable**
1. Check cloud provider status page
2. Failover to geo-redundant region (automatic if enabled)
3. If needed: Re-publish artifacts using toolkit from Git repository (< 30 minutes)

**Scenario 3: Corrupted Artifact Published**
1. Identify last known-good Git commit
2. Revert to that commit: `git revert <bad-commit>`
3. Run toolkit: `kairos-ontology project domains/ --target all`
4. Trigger CI/CD to publish corrected artifact
5. Notify consumers to update to new version

---

## Compliance Checklist (Quarterly Review)

**User Implements:** Customize checklist for your environment

- [ ] All repository access reviewed and unauthorized users removed
- [ ] Storage credentials rotated (if 90+ days old)
- [ ] Platform secrets reviewed (no expired or unused secrets)
- [ ] Gitleaks scan passing on all branches
- [ ] Dependabot/Snyk alerts reviewed and resolved
- [ ] CI/CD logs archived (if needed for compliance)
- [ ] Incident response plan tested (tabletop exercise)
- [ ] Security training completed by all team members
- [ ] Toolkit version updated to latest stable release

**Sign-Off:**
- Platform Architect: ________________ Date: ________
- Security Officer: _________________ Date: ________

---

## Summary

**Document Status:** ✅ Updated to reflect CLI Toolkit implementation

**Key Points:**
- ✅ Toolkit is a local CLI tool with minimal security surface (no server, no network)
- ✅ Toolkit validates ontologies and generates artifacts locally
- ✅ Open-source code (auditable by users)
- 📋 Authentication, authorization, encryption: **user responsibility**
- 📋 Git access control, CI/CD security: **user configures**
- 📋 Artifact publishing, storage security: **user implements**
- 📋 Compliance (GDPR, ISO 27001, SOC 2): **user's organizational responsibility**

**Toolkit Security Features:**
- ✅ Syntax and SHACL validation (prevents malformed artifacts)
- ✅ Deterministic artifact generation (reproducible builds)
- ✅ No telemetry or data collection
- ✅ No credentials required (reads local files, writes local files)

**User Security Responsibilities:**
- Git repository access control (branch protection, 2FA, etc.)
- CI/CD pipeline security (secrets management, isolation)
- Artifact storage security (encryption, access control, versioning)
- Compliance monitoring and auditing
- Incident response procedures
- [ ] Dependabot alerts reviewed and resolved
- [ ] CI/CD logs archived (if needed for compliance)
- [ ] Incident response plan tested (tabletop exercise)
- [ ] Security training completed by all team members

**Sign-Off:**
- Platform Architect: ________________ Date: ________
- Security Officer: _________________ Date: ________
