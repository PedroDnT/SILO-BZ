CREATE TABLE "planets" (
	"id" serial PRIMARY KEY,
	"name" text NOT NULL,
	"mass_kg" double precision NOT NULL,
	"temperature_celsius" integer NOT NULL
);
