# Próximos pasos remotos

Estas operaciones modifican GitHub o dependen de sus ejecutores y requieren
autorización explícita:

1. Publicar los commits locales de `main` con `git push`.
2. Observar que los workflows **Quality** y **Packages** completen todas las
   matrices en GitHub Actions antes de publicar una versión.
3. Crear y publicar la etiqueta `v2.0.0` solo después de que `main` esté verde,
   observar el workflow **Release** y comprobar que la GitHub Release contenga
   los 13 artefactos esperados más `SHA256SUMS`.
