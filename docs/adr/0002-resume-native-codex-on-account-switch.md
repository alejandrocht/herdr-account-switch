# Verificar el cambio y reanudar el hilo nativo de Codex

Codex CLI 0.167.0 mantiene las credenciales en memoria. Su AuthManager documenta
que un cambio externo del archivo no se adopta hasta una recarga explícita;
la renovación protegida rechaza una identidad distinta.

Una prueba local con esa versión, credenciales ficticias, proveedor local y un
CODEX_HOME temporal confirmó: iniciar A carga A; escribir B mantiene A en el
Agente; reiniciar el servidor carga B. No se utilizaron credenciales reales.

Usaremos un app-server hijo propio por Conversación administrada y la TUI nativa
conectada a su socket Unix privado. El protocolo del socket es WebSocket; el
adaptador usa biblioteca estándar y no abre un puerto de red. Los directorios
del socket y del estado son privados y las credenciales nunca llegan al mod.

El cambio primero valida B en un entorno temporal. Solo después, en un punto
inactivo del hilo, detiene sus procesos propios, conserva las credenciales más
recientes de A, aplica B y verifica las credenciales que cargó el servidor nuevo.
La reanudación utiliza el identificador nativo exacto, nunca fork, resumen o
reenvío del último mensaje. Un rechazo conserva A; un fallo de adopción restaura
A y reanuda ese mismo hilo. El estado diferencia solicitud, comprobación,
reanudación, adopción y fallo.

El #3 permite coordinar una Conversación compatible; la adopción en varias
pestañas se implementará en #4. Las sesiones abiertas con el lanzador anterior
no se modifican silenciosamente: se identifican y requieren reabrirse usando la
reanudación nativa antes de participar en un cambio.

Fuentes verificadas:

- [AuthManager 0.167.0](https://github.com/openai/codex/blob/rust-v0.167.0/codex-rs/login/src/auth/manager.rs)
- [Protocolo de app-server](https://learn.chatgpt.com/docs/app-server)
- [Transporte Unix](https://github.com/openai/codex/blob/rust-v0.167.0/codex-rs/app-server-transport/src/transport/unix_socket.rs)

La prueba de compatibilidad con dos Cuentas reales y un hilo con mensajes,
resultados de herramientas y trabajo local sigue siendo obligatoria para cerrar
#3; la prueba con credenciales ficticias no la sustituye.
