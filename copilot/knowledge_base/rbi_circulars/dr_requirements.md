# RBI Circular on Business Continuity Planning (BCP) & Disaster Recovery (DR)
## Reference: RBI/2023-24/85 DOR.CRE.REC.52/23.03.001/2023-24
## Applicable To: All Scheduled Commercial Banks, NBFCs, Payment System Operators

---

### Key Mandates

#### 1. Recovery Time Objective (RTO)
- **Core Banking Systems:** Maximum 4 hours
- **ATM Network:** Maximum 2 hours
- **UPI/NEFT/RTGS:** Maximum 1 hour
- **SWIFT Messaging:** Maximum 4 hours

#### 2. Recovery Point Objective (RPO)
- **Core Banking:** Maximum 15 minutes data loss
- **ATM Transactions:** Zero data loss (all transactions logged in real-time)
- **Trading Systems:** Maximum 5 minutes

#### 3. DR Testing Frequency
- **Full DR Drill:** At least once per year
- **Partial DR Test:** At least once per quarter
- **Tabletop Exercise:** At least once per month

#### 4. Network Resilience Requirements
- **Minimum two diverse paths** between HO and each ZO
- **Automatic failover** must complete within 60 seconds
- **Real-time monitoring** of all critical links with alerting threshold at 80% utilization
- **Quarterly penetration testing** of network segmentation (VRF isolation)

#### 5. Incident Reporting
- **P1 (Critical):** Report to RBI within 2 hours of detection
  - Affects &gt;5 branches OR &gt;1000 customers OR &gt;₹10 lakh financial impact
- **P2 (High):** Report within 24 hours
  - Affects 2-5 branches OR 100-1000 customers
- **P3 (Medium):** Report within 72 hours
  - Affects 1 branch OR &lt;100 customers

#### 6. Air-Gap Compliance
- **NO cloud-based AI/ML** for transaction processing or network control
- **All AI models must run on-premises** with audit trails
- **Data sovereignty:** All customer data must remain within Indian jurisdiction
- **Third-party AI tools:** Require RBI approval and security audit

---

### Penalties for Non-Compliance
| Violation | Penalty |
|-----------|---------|
| RTO exceeded by &gt;25% | ₹10 lakh per incident |
| No DR test for &gt;6 months | ₹5 lakh + license review |
| Unreported P1 incident | ₹25 lakh + regulatory action |
| Cloud AI without approval | ₹50 lakh + business restriction |

---

### Relevant to Netwroxia
Netwroxia's predictive capability directly supports RBI compliance by:
1. **Preventing RTO breaches** — Predicts failures 5-10 min before impact, enabling proactive failover
2. **Ensuring DR readiness** — Monitors DR replication lag in real-time
3. **Automated incident classification** — Auto-assigns P1/P2/P3 based on affected sites/users
4. **Air-gap verification** — All AI runs locally, zero cloud dependency
5. **Audit trail generation** — Every prediction and remediation action is logged with timestamp
