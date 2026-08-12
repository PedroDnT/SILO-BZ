select schema_name from information_schema.schemata
where schema_name not like 'pg_%' and schema_name <> 'information_schema'
