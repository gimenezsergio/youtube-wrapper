# Despliegue de actualización diaria

La actualización automática reutiliza la cola y el worker existentes. El timer
solo crea un trabajo con las etapas `subscriptions`, `followed_videos` y
`discovery`. Si ya existe un trabajo pendiente o en ejecución, no crea otro.

## Horario

`youtube-curator-refresh.timer` se ejecuta diariamente a las 08:00 en
`America/Argentina/Buenos_Aires`, con una demora aleatoria máxima de dos minutos.
`Persistent=true` recupera una ejecución perdida si el servidor estuvo apagado.

## Instalación en producción

Copiar `youtube-curator-refresh.service` y `youtube-curator-refresh.timer` desde
`deploy/systemd/` a `/etc/systemd/system/`, ejecutar `systemctl daemon-reload` y
habilitar el timer con `systemctl enable --now youtube-curator-refresh.timer`.

## Verificación

Ejecutar manualmente `systemctl start youtube-curator-refresh.service`, revisar
`journalctl -u youtube-curator-refresh.service` y confirmar el nuevo registro en
`refresh_runs`. La segunda ejecución inmediata debe informar
`refresh_already_active` sin crear un duplicado.

Los archivos con sufijo `-staging` aíslan la validación en el puerto, proceso y
base de datos de staging. No deben reutilizarse contra producción.

## Entorno de staging

Staging usa un único worktree en `/opt/youtube-wrapper/staging` y un entorno
virtual propio en `/opt/youtube-wrapper/staging/.venv`. Crear ese entorno con
`python3 -m venv .venv` e instalar `requirements.lock`. Las unidades web,
worker y refresh con sufijo `-staging` apuntan exclusivamente a esas rutas y a
`/var/lib/youtube-curator-staging/.env`.

Las unidades de staging incluyen límites de CPU, memoria y tareas para evitar
que una prueba defectuosa agote los recursos compartidos con producción.

## Desinstalación

Ejecutar `systemctl disable --now youtube-curator-refresh.timer`, retirar las dos
unidades instaladas y ejecutar `systemctl daemon-reload`.
