select routine_name from information_schema.routines
where routine_name like 'fraud_screen%' or routine_name like 'fund_performance%'
