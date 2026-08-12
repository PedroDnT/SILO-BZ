select 'FI diário'     as dataset, count(*) as rows from cvm_fi_diario
union all select 'FIDC mensal',   count(*) from cvm_fidc_mensal
union all select 'FII mensal',    count(*) from cvm_fii_mensal
union all select 'SECURIT série', count(*) from cvm_securit_serie
