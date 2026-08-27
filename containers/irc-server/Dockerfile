FROM inspircd/inspircd-docker:latest

COPY inspircd.conf /inspircd/conf/inspircd.conf

# The upstream image declares its non-root user by name. Kubernetes cannot
# verify a named image user when runAsNonRoot is enabled, so record the known
# numeric InspIRCd UID in the derived image metadata.
USER 10000
