# ADR 0005: GitOps promotion by digest, signed images, no static CI credentials

**Status:** accepted

## Decision
1. CI builds once per commit, scans with Trivy (fail on fixable HIGH/CRITICAL), attaches an SBOM and build provenance, and signs the image **by digest** with keyless cosign (GitHub OIDC identity, recorded in the Rekor transparency log).
2. Promotion is a commit: CI writes the new digest into `deploy/helm/payments/values-aws.yaml`. Argo CD deploys whatever Git says. Rollback is `git revert`.
3. CI never holds AWS keys. A read-only IAM role trusts GitHub's OIDC provider, limited to this repository's pull requests and `main` branch, for `terraform plan`. Applies stay manual.

## Consequences
- Every running pod can be traced to an image digest, a signature, an SBOM and a commit.
- **Next:** admission-time signature verification (Kyverno or the sigstore policy-controller) so unsigned images cannot run, and pinning third-party actions by commit SHA.
- The bump commit pushes to `main`; with branch protection, allow the `github-actions[bot]` or switch to an auto-merged PR.
