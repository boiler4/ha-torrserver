# Security policy

Do not open a public issue for a vulnerability or include credentials in logs or
diagnostics. Use GitHub's private vulnerability reporting for this repository if
it is enabled; otherwise contact the repository owner privately through GitHub.

The integration sends credentials only to the single TorrServer URL selected by
the user. Automatic discovery is credential-free. Prefer HTTPS when Basic
authentication is used outside a fully trusted local network.
