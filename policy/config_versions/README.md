Archived policy bundle versions for activation/rollback.

policy-3.3.1/ : active successor with the German explicit-self-exclusion safety correction.
policy-3.3.0/ : preserved failed optional-local-model candidate (adds model_configuration).
policy-3.2.0/ : rules-only rollback target retaining Phase 03D detector hardening.
policy-3.1.0/ : earlier derived-refinement bundle.
policy-3.0.0/ : pre-derived rollback target.

Phase 04 rollback: replace policy/configuration_manifest.json with the policy-3.2.0
manifest and remove policy/model_configuration.json. The loader then exposes no model
configuration and rules-only operation remains available. Activation restores the
policy-3.3.0 manifest and model_configuration component.
