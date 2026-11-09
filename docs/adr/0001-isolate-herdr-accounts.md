# Aislar las cuentas administradas por Herdr

El selector administrará cuentas de Codex y Claude exclusivamente para Herdr,
con un cambio compartido entre las pestañas del mismo agente y sin modificar
el login de Deska u otras aplicaciones. Sus credenciales y estado de cuentas
se mantendrán aislados de los almacenes usados por esas aplicaciones,
aceptando un registro inicial por cuenta para conservar esa separación.
Reutilizar directamente el almacén predeterminado simplificaría la integración,
pero extendería el cambio de cuenta fuera de la frontera elegida por el usuario.
