Archived policy bundle versions for activation/rollback.

policy-3.1.0/ : active bundle (adds the derived_refinement_rules component).
policy-3.0.0/ : rollback target (no derived_refinement_rules component; pre-derived behavior).

Rollback: replace policy/configuration_manifest.json with the policy-3.0.0 manifest and
remove policy/derived_refinement_rules.json. The loader then loads no derived rules, so the
engine reproduces the pre-derived (Phase 03A) behavior. Activation reverses this.
