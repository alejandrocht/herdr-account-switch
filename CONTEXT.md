# Agent Account Switching

Vocabulario para seleccionar cuentas de Codex y Claude conservando las
conversaciones de trabajo.

## Language

**Agente**:
La herramienta de trabajo que mantiene una conversación y ejecuta acciones,
como Codex o Claude Code.

**Cuenta**:
La identidad autenticada de una persona ante el servicio de un agente, con
sus propios permisos y cupos de uso.
_Avoid_: Conversación, perfil.

**Perfil de cuenta**:
El registro local con nombre que identifica una cuenta guardada y permite
seleccionarla nuevamente.
_Avoid_: Conversación, pestaña.

**Cuenta activa**:
La cuenta seleccionada para las próximas solicitudes de las sesiones que
comparten un mismo cambio de cuenta.

**Conversación**:
El historial de mensajes y resultados de acciones correspondiente a un hilo
de trabajo de un agente.
_Avoid_: Cuenta, inicio de sesión.

**Cambio compartido**:
La selección de una cuenta activa para varias sesiones del mismo agente;
cada sesión conserva su propia conversación.
_Avoid_: Fusión de conversaciones, fusión de cuentas.

**Continuidad de conversación**:
La conservación de la conversación y del trabajo realizado al cambiar de
cuenta, sin sustituir el hilo por un resumen nuevo.

**Cupo de uso**:
La capacidad de uso que el servicio concede a una cuenta durante sus
ventanas de consumo.
_Avoid_: Credencial, token de acceso.

**Credencial de acceso**:
Los datos de autenticación que permiten realizar solicitudes con una cuenta.
_Avoid_: Cupo de uso, tokens disponibles.
