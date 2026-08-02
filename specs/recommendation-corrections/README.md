# Correcciones de recomendaciones — paquete SDD incremental

Este paquete define la estabilización del motor de recomendaciones ya integrado en `main`. No reemplaza la especificación general de YouTube Curator: agrega decisiones verificables y puertas de ejecución para corregir defectos observados después del primer incremento.

## Referencia

- Repositorio: `gimenezsergio/youtube-wrapper`.
- Commit auditado: `99023ae` (`d733625` integrado mediante PR #2).
- Alcance: recomendaciones, refresh worker, feedback, contratos relacionados, configuración y migraciones del incremento de descubrimiento.
- Fuera de alcance: rediseño visual general, clasificación automática completa y funciones ajenas a descubrimiento.

## Documentos

1. `current-state.md`: evidencia reproducida y brechas del commit auditado.
2. `requirements.md`: comportamiento correctivo obligatorio.
3. `design.md`: decisiones internas congeladas para eliminar ambigüedades.
4. `tests.md`: escenarios ejecutables y resultados exactos.
5. `tasks.md`: ejecución en baby steps, empezando por pruebas rojas.

## Precedencia

Dentro del alcance de este paquete, la precedencia es:

1. `requirements.md` de este directorio.
2. `specs/openapi.yaml`.
3. `design.md` de este directorio.
4. `tests.md` de este directorio.
5. Los documentos generales de `specs/`.
6. `current-state.md` y `tasks.md` de este directorio, que son informativos y operativos.

La precedencia correctiva solo aplica cuando estos documentos precisan o corrigen el incremento de recomendaciones. El resto de los requisitos generales conserva plena vigencia.

## Método de ejecución

Cada cambio sigue esta secuencia obligatoria:

```text
regla de especificación
→ prueba de regresión roja por el motivo esperado
→ cambio mínimo de producción
→ prueba específica verde
→ suite y calidad verdes
→ commit acotado
```

No se autoriza implementar todas las fases en una sola pasada. La fase siguiente comienza únicamente después de revisar la evidencia de la anterior.

## Regla para agentes

Un agente implementador debe:

- leer los cinco documentos completos;
- trabajar desde el `main` actualizado en una rama nueva;
- no modificar requisitos para adaptar el contrato al código existente;
- no borrar ni debilitar pruebas;
- no mezclar pruebas rojas y correcciones de producción en el primer commit;
- informar comandos, salidas, commit y puntos pendientes después de cada fase;
- detenerse en la puerta indicada, sin continuar automáticamente a la siguiente fase.
