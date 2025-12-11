# SQL Fake Data Generator - Stored Procedure Library

This document describes the stored procedures and helper functions implemented in PostgreSQL
for deterministic fake user data generation.

The main goals of the library are:

- all randomness is implemented in SQL,
- all generated data is deterministic and depends on `(locale, seed, batch_index, index_in_batch)`,
- the implementation is split into small, reusable functions (PRNG, normal distribution, geo coordinates, names, addresses, phone numbers, e-mails).

Below is the detailed description of each function.

1. Data Model Overview
1.1 Enum and composite types
CREATE TYPE name_type AS ENUM ('first', 'middle', 'last', 'title');

CREATE TYPE fake_user AS (
    full_name   TEXT,
    address     TEXT,
    latitude    DOUBLE PRECISION,
    longitude   DOUBLE PRECISION,
    height_cm   DOUBLE PRECISION,
    weight_kg   DOUBLE PRECISION,
    eye_color   TEXT,
    phone       TEXT,
    email       TEXT
);

1.2 Lookup tables

All lookup data is shared between locales using a locale column:

names(locale, name_type, gender, value) – first/middle/last names and titles.

cities(locale, name)

streets(locale, name)

postal_codes(locale, postal_code)

email_domains(locale, domain)

phone_formats(locale, pattern) – templates like +1 (XXX) XXX-XXXX, 0XXX XXXXXXX.

eye_colors(locale, color_name)

physical_config(locale, height_mean_cm, height_std_cm, weight_mean_kg, weight_std_kg) – parameters of normal distributions for height and weight.

The library does not hard-code any specific names or phrases in the functions.
To extend or improve realism, it is enough to insert new rows into these tables.

2. Deterministic Random Number Generation

To guarantee reproducibility, all randomness is implemented using a simple deterministic PRNG (linear congruential generator) implemented as SQL functions.

2.1 prng_next(state BIGINT) → BIGINT

Purpose: LCG step function used internally.

Arguments:

Name	Type	Description
state	BIGINT	Current PRNG state (1 … 2³¹−1).

Algorithm:

new_state := (1103515245 * state + 12345) % 2147483648;


Modulus = 2³¹ (2147483648).

If result is 0, it is replaced by 1.

The function is IMMUTABLE, so for the same state it always returns the same new_state.

2.2 prng_init(p_locale, p_seed, p_batch_index, p_index_in_batch, p_stream) → BIGINT

Purpose: Initialize a PRNG state that uniquely corresponds to:

locale,

global seed,

batch index,

index within batch,

logical “stream” (separate stream per attribute).

Arguments:

Name	Type	Description
p_locale	TEXT	Locale identifier (e.g. 'en_US', 'de_DE').
p_seed	INT	Global integer seed provided by the user.
p_batch_index	INT	Zero-based batch index.
p_index_in_batch	INT	Zero-based index within the batch.
p_stream	INT	Stream ID to separate randomness of different attributes (names, email…).

Algorithm (simplified):

st := p_seed * 31
    + p_batch_index * 131
    + p_index_in_batch * 1009
    + p_stream * 65537
    + abs(hashtext(p_locale));

st := abs(st) % 2147483648;
if st = 0 then st := 1; end if;


This guarantees that:

changing any of locale, seed, batch_index, index_in_batch, or stream changes the random sequence,

for fixed values, the sequence is always identical (reproducible).

2.3 rand_uniform_01(p_locale, p_seed, p_batch_index, p_index_in_batch, p_stream) → DOUBLE PRECISION

Purpose: Generate a reproducible uniform random variable in (0, 1).

Algorithm:

Compute initial state via prng_init(...).

Apply prng_next(state).

Return state / 2147483648.0.

2.4 rand_normal(..., p_mean, p_stddev) → DOUBLE PRECISION

Signature:

rand_normal(
    p_locale         TEXT,
    p_seed           INT,
    p_batch_index    INT,
    p_index_in_batch INT,
    p_stream         INT,
    p_mean           DOUBLE PRECISION,
    p_stddev         DOUBLE PRECISION
)


Purpose: Generate a deterministic normally distributed value.

Algorithm (Box–Muller transform):

Generate u1, u2 ~ Uniform(0,1) using two independent streams:

u1 := rand_uniform_01(..., p_stream);
u2 := rand_uniform_01(..., p_stream + 1);


Compute standard normal:

z0 := sqrt(-2 * ln(u1)) * cos(2 * pi() * u2);


Scale and shift:

return p_mean + p_stddev * z0;


Used for:

height (cm) and weight (kg), with parameters taken from physical_config.

2.5 rand_on_sphere(p_locale, p_seed, p_batch_index, p_index_in_batch, p_stream) → TABLE(lat, lon)

Purpose: Generate a random point uniformly distributed on the surface of a unit sphere.

Algorithm:

Sample two uniforms:

u1 := rand_uniform_01(..., p_stream);
u2 := rand_uniform_01(..., p_stream + 1);


Use the standard algorithm for uniform sampling on a sphere:

z   := 2 * u1 - 1;          -- cos(theta) uniformly in [-1,1]
phi := 2 * pi() * u2;       -- longitude ∈ [0, 2π)
lat_rad := asin(z);
lon_rad := phi - pi();      -- shift to [-π, π]


Convert to degrees:

lat := lat_rad * 180 / pi();
lon := lon_rad * 180 / pi();


Resulting latitude and longitude have constant probability density on the sphere.

3. Name and Title Helpers
3.1 pick_random_name(p_locale, p_seed, p_batch_index, p_index_in_batch, p_stream, p_type) → TEXT

Purpose: Pick a random name (first/middle/last) for a locale, ignoring gender.

Arguments:

Name	Type	Description
p_locale	TEXT	Locale (en_US, de_DE, …).
p_seed	INT	Global seed.
p_batch_index	INT	Batch index.
p_index_in_batch	INT	Index in batch.
p_stream	INT	PRNG stream for this selection.
p_type	name_type	'first', 'middle', 'last', 'title'.

Algorithm:

Count candidates:

SELECT COUNT(*) INTO cnt
FROM names
WHERE locale = p_locale AND name_type = p_type;


Draw uniform u and compute offset floor(u * cnt).

Select:

SELECT value INTO result
FROM names
WHERE locale = p_locale AND name_type = p_type
ORDER BY id
OFFSET offset_ LIMIT 1;

3.2 pick_random_name_g(..., p_type, p_gender) → TEXT

Same as above, but gender-aware.

Additional filter:

WHERE locale = p_locale
  AND name_type = p_type
  AND (
        p_gender IS NULL
        OR gender = p_gender
        OR gender IS NULL   -- gender-neutral rows are allowed
      )


Used for:

first names (gender specific),

middle names (often gender-neutral, so p_gender is NULL).

3.3 pick_title_for_gender(p_locale, ..., p_stream, p_gender) → TEXT

Purpose: Generic gender-aware title selection (e.g. Ms., Mrs., Madam, Dr., Prof., Herr, Frau).

Filter:

WHERE locale = p_locale
  AND name_type = 'title'
  AND (
        (p_gender = 'M' AND (gender = 'M' OR gender IS NULL))
     OR (p_gender = 'F' AND (gender = 'F' OR gender IS NULL))
      )


If no rows exist for given locale + gender, returns NULL.

3.4 pick_male_title(p_locale, ..., p_stream) → TEXT

Purpose: Special handling for male titles in en_US.

For p_locale = 'en_US':

Search names for title values starting with Mr. and Sir.

Deterministic ratio: for each user i in the batch:

IF (p_index_in_batch % 3) = 2 THEN
    RETURN 'Sir';   -- roughly 1/3 of male titles
ELSE
    RETURN 'Mr.';   -- roughly 2/3 of male titles
END IF;


For other locales:

Delegates to pick_title_for_gender(..., 'M') (e.g. Herr, Dr., Prof. for de_DE).

This gives realistic mixture of Mr. and Sir without separate randomness.

4. Other Lookup Helpers
4.1 pick_random_eye_color(p_locale, ..., p_stream) → TEXT

Random eye color, uniformly selected from eye_colors for given locale.

5. Component Generators
5.1 gen_full_name(p_locale, p_seed, p_batch_index, p_index_in_batch) → TEXT

Purpose: Generate a full human name with optional title and middle name.

Algorithm details:

Gender choice – deterministic:

IF (p_index_in_batch % 2) = 0 THEN
    person_gender := 'M';
ELSE
    person_gender := 'F';
END IF;


Title / middle flags:

use_title  := rand_uniform_01(..., 100) < 0.30;  -- ~30% users have a title
use_middle := rand_uniform_01(..., 101) < 0.40;  -- ~40% users have middle name


Title:

If use_title = TRUE:

male: pick_male_title(...),

female: pick_title_for_gender(..., 'F').

Otherwise title := NULL.

Names:

first_name := pick_random_name_g(..., 'first', person_gender);
last_name  := pick_random_name(..., 'last');
IF use_middle THEN
    middle_name := pick_random_name_g(..., 'middle', NULL);
ELSE
    middle_name := NULL;
END IF;


Formatting:

RETURN TRIM(BOTH ' ' FROM CONCAT_WS(' ', title, first_name, middle_name, last_name));


Examples:

SELECT gen_full_name('en_US', 123, 0, 0);
-- "Mr. Ethan Taylor Richardson"

SELECT gen_full_name('de_DE', 123, 0, 1);
-- "Frau Anna Maria Müller"  (example; depends on lookup data)

5.2 gen_address(p_locale, p_seed, p_batch_index, p_index_in_batch) → TEXT

Purpose: Generate a localized postal address.

Logic:

Randomly pick:

street from streets(locale),

city from cities(locale),

pc from postal_codes(locale),

using the same uniform/offset mechanism as for names.

Random house number between 1 and 200.

Formatting depends on locale:

en_US:

<house> <street>, <city> <postal_code>


de_DE:

<street> <house>, <postal_code> <city>


Example:

SELECT gen_address('en_US', 123, 0, 0);
-- "9 Valley Road, Minneapolis 37203"

SELECT gen_address('de_DE', 123, 0, 0);
-- "Bahnhofstraße 12, 10115 Berlin"

5.3 gen_phone(p_locale, p_seed, p_batch_index, p_index_in_batch) → TEXT

Purpose: Generate phone numbers using locale-specific patterns.

Algorithm:

Pick a random pattern from phone_formats(locale, pattern):

SELECT pf.pattern INTO v_pattern
FROM phone_formats pf
WHERE pf.locale = p_locale
ORDER BY pf.id
OFFSET offset_ LIMIT 1;


Iterate over characters in v_pattern:

If character = 'X', replace with a random digit 0–9 using rand_uniform_01 with offset based on position.

Otherwise, copy the character as-is.

Patterns can be:

'+1 (XXX) XXX-XXXX' for en_US,

'+49 (0XXX) XXXXXXX' or '0XXX XXXXXXX' for de_DE, etc.

5.4 gen_email(p_locale, p_seed, p_batch_index, p_index_in_batch) → TEXT

Purpose: Generate realistic email addresses from the full name and locale-specific domains.

Algorithm:

Domain selection:

Uniformly pick a domain from email_domains(locale).

Name tokens:

Call gen_full_name(...) to get a full name.

Split into tokens (regexp_split_to_array).

If first token is a known title ('Mr.', 'Sir', 'Ms.', 'Mrs.', 'Madam', 'Dr.', 'Prof.', 'Herr', 'Frau'), skip it.

Use first name token as first_raw, last token as last_raw.

Sanitization:

first := lower(regexp_replace(first_raw, '[^a-zA-Z0-9]', '', 'g'));
last  := lower(regexp_replace(last_raw,  '[^a-zA-Z0-9]', '', 'g'));


If any becomes empty, it falls back to "user" / "name".

Numeric suffix:

Generate num ∈ [0, 99] deterministically via rand_uniform_01.

Username pattern:

Choose one of several formats based on another random draw:

first.last

first.lastNN

f.lastNN (initial + last name)

first_lNN (first name + last initial)

Example usernames: ethan.richardson79, k.palmer91, ava_m26.

Combine:

username || '@' || domain


Examples:

SELECT gen_email('en_US', 123, 0, 0);
-- "ethan.richardson79@outlook.com"

SELECT gen_email('de_DE', 123, 0, 0);
-- "anna.schmidt14@mailbox.org"

6. Main Generators
6.1 generate_fake_users(p_locale, p_seed, p_batch_size, p_batch_index) → SETOF fake_user

Purpose: Main entry point – generate a batch of fake users.

Arguments:

Name	Type	Description
p_locale	TEXT	Locale identifier (en_US, de_DE, …).
p_seed	INT	Global deterministic seed.
p_batch_size	INT	Number of users to generate in this batch.
p_batch_index	INT	Zero-based batch index (allows paging with the same seed & locale).

Algorithm:

Read physical parameters for the locale:

SELECT * INTO cfg
FROM physical_config
WHERE locale = p_locale;


For each i from 0 to p_batch_size - 1:

full_name := gen_full_name(p_locale, p_seed, p_batch_index, i)

address := gen_address(p_locale, p_seed, p_batch_index, i)

(lat, lon) := rand_on_sphere(p_locale, p_seed, p_batch_index, i, 300)

height_cm := rand_normal(p_locale, p_seed, p_batch_index, i, 400, cfg.height_mean_cm, cfg.height_std_cm)

weight_kg := rand_normal(p_locale, p_seed, p_batch_index, i, 410, cfg.weight_mean_kg, cfg.weight_std_kg)

eye_color := pick_random_eye_color(p_locale, p_seed, p_batch_index, i, 420)

phone := gen_phone(p_locale, p_seed, p_batch_index, i)

email := gen_email(p_locale, p_seed, p_batch_index, i)

Return each constructed fake_user row.

Reproducibility guarantee:

For fixed (p_locale, p_seed, p_batch_index) and given i, all attributes are fully deterministic because:

PRNG state initialization depends on these values + fixed per-attribute p_stream.

Examples:

Generate first 10 users for English (USA):

SELECT *
FROM generate_fake_users('en_US', 123, 10, 0);


Next batch with the same parameters:

SELECT *
FROM generate_fake_users('en_US', 123, 10, 1);


Same call repeated ⇒ identical results.

6.2 benchmark_generate_fake_users(p_locale, p_seed, p_batch_size, p_batch_index, p_iterations)

Purpose: Measure throughput of the generator (users/second).

Returns a single row:

Column	Type	Description
total_users	INT	p_batch_size * p_iterations.
total_time_seconds	DOUBLE PRECISION	Wall-clock time measured via clock_timestamp().
users_per_second	DOUBLE PRECISION	total_users / total_time_seconds.

Algorithm:

t_start := clock_timestamp().

Loop i = 1 .. p_iterations:

PERFORM * FROM generate_fake_users(p_locale, p_seed, p_batch_size, p_batch_index + i - 1);

t_end := clock_timestamp().

Compute metrics and return.

Example:

SELECT *
FROM benchmark_generate_fake_users('en_US', 123, 10000, 0, 10);