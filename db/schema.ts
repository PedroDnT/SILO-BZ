import { doublePrecision, integer, pgTable, serial, text } from 'drizzle-orm/pg-core'

export const planets = pgTable('planets', {
  id: serial('id').primaryKey(),
  name: text('name').notNull(),
  massKg: doublePrecision('mass_kg').notNull(),
  temperatureCelsius: integer('temperature_celsius').notNull(),
})
