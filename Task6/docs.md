# SQL Fake Data Generator - Stored Procedure Library

This document describes the stored procedures and helper functions implemented in PostgreSQL
for deterministic fake user data generation.

The main goals of the library are:

- all randomness is implemented in SQL,
- all generated data is deterministic and depends on `(locale, seed, batch_index, index_in_batch)`,
- the implementation is split into small, reusable functions (PRNG, normal distribution, geo coordinates, names, addresses, phone numbers, e-mails).

Below is the detailed description of each function.

The main entry point is the function:

generate_fake_users(
    p_locale      text,
    p_seed        int,
    p_batch_size  int,
    p_batch_index int
) RETURNS SETOF fake_user

which is called from the web application.

1. Random number utilities
1.1. prng_next

Name: prng_next

Signature:

prng_next(state bigint) RETURNS bigint


Parameters:

state – current internal state of the pseudo-random number generator
(an integer in the range 0 < state < 2^31).

Description:

Implements one step of a Linear Congruential Generator (LCG):

state_{n+1} = (a * state_n + c) mod m

with constants:

a = 1103515245

c = 12345

m = 2^31

The function is declared IMMUTABLE, so the same input always produces the same output.

Example:

SELECT prng_next(12345);

1.2. prng_init

Name: prng_init

Signature:

prng_init(
    p_locale         text,
    p_seed           int,
    p_batch_index    int,
    p_index_in_batch int,
    p_stream         int
) RETURNS bigint


Parameters:

p_locale – locale code (e.g. 'en_US', 'de_DE').

p_seed – user-provided seed.

p_batch_index – batch index (0, 1, 2, …).

p_index_in_batch – index of a record within the batch (0 .. batch_size - 1).

p_stream – logical stream identifier (different for names, addresses, phones, etc.).

Description:

Mixes all parameters into a single deterministic initial PRNG state. It:

Combines p_seed, p_batch_index, p_index_in_batch, p_stream and a hash of p_locale (hashtext(p_locale)).

Reduces the result modulo 2^31.

Ensures that the final state is not zero (if zero, replaces with 1).

This guarantees that the same combination of (locale, seed, batch_index, index_in_batch, stream) always produces the same initial PRNG state, and therefore reproducible random values.

Example:

SELECT prng_init('en_US', 123, 0, 0, 1);

1.3. rand_uniform_01

Name: rand_uniform_01

Signature:

rand_uniform_01(
    p_locale         text,
    p_seed           int,
    p_batch_index    int,
    p_index_in_batch int,
    p_stream         int
) RETURNS double precision


Parameters: same as in prng_init.

Description:

Returns a reproducible uniform random value in the open interval (0, 1):

Initializes the internal state using prng_init(...).

Applies one prng_next step.

Divides the resulting integer by 2^31 to obtain a double in (0,1).

The function is IMMUTABLE, therefore deterministic for a given set of arguments.

Example:

SELECT rand_uniform_01('en_US', 123, 0, 0, 10);

1.4. rand_normal

Name: rand_normal

Signature:

rand_normal(
    p_locale         text,
    p_seed           int,
    p_batch_index    int,
    p_index_in_batch int,
    p_stream         int,
    p_mean           double precision,
    p_stddev         double precision
) RETURNS double precision


Parameters:

p_locale, p_seed, p_batch_index, p_index_in_batch, p_stream – as above.

p_mean – mean of the desired normal distribution.

p_stddev – standard deviation of the desired normal distribution.

Description:

Generates a normally distributed random variable using the Box–Muller transform:

Generates two independent uniform variables u1, u2 ~ U(0,1) by calling
rand_uniform_01 for streams p_stream and p_stream + 1.

Applies the Box–Muller formula:

z0 = sqrt(-2 * ln(u1)) * cos(2π * u2)    ~ N(0,1)


Scales and shifts to obtain N(p_mean, p_stddev^2):

value = p_mean + p_stddev * z0


This function is used to generate physical attributes such as height and weight.

Example:

SELECT rand_normal('en_US', 123, 0, 5, 400, 175.0, 10.0);

1.5. rand_on_sphere

Name: rand_on_sphere

Signature:

rand_on_sphere(
    p_locale         text,
    p_seed           int,
    p_batch_index    int,
    p_index_in_batch int,
    p_stream         int
) RETURNS TABLE(lat double precision, lon double precision)


Parameters: same as in other random functions.

Description:

Generates a random point uniformly distributed on the surface of the sphere, and returns its geographic coordinates (latitude and longitude in degrees).

Algorithm:

Generate two uniforms u1, u2 ~ U(0,1).

Compute:

z = 2*u1 - 1 (height coordinate, uniform in [-1, 1])

phi = 2π*u2 (angle in the XY plane)

Compute spherical coordinates:

latitude (in radians): lat = asin(z) (range [-π/2, π/2])

longitude (in radians): lon = phi - π (range [-π, π])

Convert to degrees:

lat_deg = lat * 180 / π

lon_deg = lon * 180 / π

Example:

SELECT * FROM rand_on_sphere('en_US', 123, 0, 0, 300);

2. Lookup helper functions (names and titles)
2.1. pick_random_name

Name: pick_random_name

Signature:

pick_random_name(
    p_locale         text,
    p_seed           int,
    p_batch_index    int,
    p_index_in_batch int,
    p_stream         int,
    p_type           name_type
) RETURNS text


Parameters:

p_locale, p_seed, p_batch_index, p_index_in_batch, p_stream – as above.

p_type – name type enum ('first', 'middle', 'last', 'title').

Description:

Picks a deterministic “random” name from the names lookup table:

Counts all names for the given (locale, name_type).

Generates a uniform u ~ U(0,1).

Computes an offset offset = floor(u * count).

Selects the row from names with that offset (ordered by id) and returns its value.

This version does not filter by gender.

Example:

SELECT pick_random_name('en_US', 123, 0, 0, 10, 'last');

2.2. pick_random_name_g (gender-aware)

Name: pick_random_name_g

Signature:

pick_random_name_g(
    p_locale         text,
    p_seed           int,
    p_batch_index    int,
    p_index_in_batch int,
    p_stream         int,
    p_type           name_type,
    p_gender         text
) RETURNS text


Parameters:

p_locale, p_seed, p_batch_index, p_index_in_batch, p_stream – as above.

p_type – name type ('first', 'middle', 'last', 'title').

p_gender – 'M', 'F' or NULL.

Description:

Gender-aware version of pick_random_name. The p_gender filter is interpreted as:

If p_gender IS NULL → no gender filtering, all rows with given (locale, type) are considered.

If p_gender = 'M' or 'F' → the function selects rows where:

gender = p_gender, or

gender IS NULL (gender-neutral rows, e.g. Dr. or gender-neutral middle names).

The selection is otherwise the same as in pick_random_name:

Count all matching rows.

Generate u ~ U(0,1).

Compute offset = floor(u * count).

Pick the row ordered by id with that offset.

Example:

-- male first name
SELECT pick_random_name_g('en_US', 123, 0, 0, 11, 'first', 'M');

-- female title (Ms./Mrs./Madam/Dr./Prof.)
SELECT pick_random_name_g('en_US', 123, 0, 0, 10, 'title', 'F');

2.3. pick_title_for_gender

Name: pick_title_for_gender

Signature:

pick_title_for_gender(
    p_locale         text,
    p_seed           int,
    p_batch_index    int,
    p_index_in_batch int,
    p_stream         int,
    p_gender         text
) RETURNS text


Parameters:

p_locale, p_seed, p_batch_index, p_index_in_batch, p_stream.

p_gender – 'M' or 'F'.

Description:

Helper function for selecting localized titles from names for a given gender:

For p_gender = 'M':

considers rows with name_type = 'title' and gender = 'M' or gender IS NULL.

For p_gender = 'F':

considers rows with name_type = 'title' and gender = 'F' or gender IS NULL.

Selection uses uniform random u ~ U(0,1) and offset logic as in pick_random_name_g.

For example, for de_DE, titles like Herr (M), Frau (F), Dr. (NULL), Prof. (NULL) can be selected this way.

Example:

-- female titles in en_US: Ms., Mrs., Madam, plus Dr./Prof.
SELECT pick_title_for_gender('en_US', 123, 0, 0, 10, 'F');

2.4. pick_male_title (specialized for en_US)

Name: pick_male_title

Signature:

pick_male_title(
    p_locale         text,
    p_seed           int,
    p_batch_index    int,
    p_index_in_batch int,
    p_stream         int
) RETURNS text


Parameters: same as above.

Description:

Specialized helper for male titles:

For p_locale = 'en_US':

picks between "Mr." and "Sir" with a deterministic 2:1 ratio based on p_index_in_batch:

if p_index_in_batch % 3 = 2 → returns "Sir" (about 1/3 of male titles),

otherwise → returns "Mr." (about 2/3 of male titles).

the actual strings are read from the names table (locale='en_US', name_type='title', value LIKE 'Mr.%' / 'Sir%').

For other locales (e.g. de_DE):

the function delegates to pick_title_for_gender(..., 'M') and uses the localized male titles (e.g. Herr, Dr., Prof.).

This ensures:

en_US male users use Mr./Sir with controlled distribution,

other locales never accidentally get "Mr."/"Sir".

Example:

-- en_US male title
SELECT pick_male_title('en_US', 123, 0, 4, 10);

-- de_DE male title (will return e.g. "Herr")
SELECT pick_male_title('de_DE', 123, 0, 4, 10);

3. Component generators
3.1. gen_full_name

Name: gen_full_name

Signature:

gen_full_name(
    p_locale         text,
    p_seed           int,
    p_batch_index    int,
    p_index_in_batch int
) RETURNS text


Description:

Generates a full name with:

deterministic gender,

optional title (Mr./Sir/Herr/Ms./Mrs./Madam/Dr./Prof.),

optional middle name,

localized first and last names.

Algorithm:

Gender determination (deterministic):

Even p_index_in_batch → male ('M'),

Odd p_index_in_batch → female ('F').

Use title / middle name:

use_title is TRUE with probability use_title_prob = 0.30 (30% of users get a title), using rand_uniform_01.

use_middle is TRUE with probability 0.40.

Title:

If use_title = TRUE:

For males:

Calls pick_male_title(...), which:

For en_US returns "Mr." or "Sir" in a deterministic 2:1 ratio.

For other locales (e.g. de_DE) uses pick_title_for_gender(..., 'M') to get titles like Herr, Dr., etc.

For females:

Calls pick_title_for_gender(..., 'F'), which selects among female and neutral titles:

example en_US: Ms., Mrs., Madam, Dr., Prof.

example de_DE: Frau, Dr., Prof.

First name:

Calls pick_random_name_g(..., 'first', person_gender) to select a gender-consistent first name.

Last name:

Calls pick_random_name(..., 'last') without gender filter.

Middle name:

If use_middle = TRUE:

Calls pick_random_name_g(..., 'middle', NULL) to select from gender-neutral middle names.

Otherwise middle_name is NULL.

Final formatting:

Concatenates (if not null): title, first_name, middle_name, last_name, separated by single spaces.

Trims leading/trailing spaces.

This function is fully deterministic for a given (locale, seed, batch_index, index_in_batch).

Example:

SELECT gen_full_name('en_US', 123, 0, 0); -- e.g. "Mr. James Lee Smith"
SELECT gen_full_name('de_DE', 123, 0, 1); -- e.g. "Frau Anna Maria Müller"

3.2. gen_address

Name: gen_address

Signature:

gen_address(
    p_locale         text,
    p_seed           int,
    p_batch_index    int,
    p_index_in_batch int
) RETURNS text


Description:

Generates a textual address using lookup tables streets, cities, and postal_codes, with a format depending on the locale.

Steps:

Validates that there is at least one street, city and postal code for the given locale.

Uses rand_uniform_01 with different streams to deterministically select:

a street name from table streets,

a city name from table cities,

a postal code from table postal_codes.

Generates a house number N in the range [1, 200].

Formats the final address:

For en_US, e.g.:
HOUSE_NUMBER STREET_NAME, CITY_NAME POSTAL_CODE
Example: 177 Maple Avenue, Boston 10123

For de_DE, e.g.:
STREET_NAME HOUSE_NUMBER, POSTAL_CODE CITY_NAME
Example: Hauptstraße 12, 10115 Berlin

For unsupported locales a generic fallback can be used.

Example:

SELECT gen_address('en_US', 123, 0, 0);
SELECT gen_address('de_DE', 123, 0, 1);

3.3. pick_random_eye_color

Name: pick_random_eye_color

Signature:

pick_random_eye_color(
    p_locale         text,
    p_seed           int,
    p_batch_index    int,
    p_index_in_batch int,
    p_stream         int
) RETURNS text


Description:

Deterministically selects an eye color for the given locale:

Counts rows in eye_colors where locale = p_locale.

Generates a uniform u ~ U(0,1).

Computes an offset and selects the corresponding color_name.

Example colors:

en_US: blue, brown, green, hazel, gray, amber.

de_DE: blau, braun, grün, grau, bernstein.

Example:

SELECT pick_random_eye_color('en_US', 123, 0, 0, 420);

3.4. gen_phone

Name: gen_phone

Signature:

gen_phone(
    p_locale         text,
    p_seed           int,
    p_batch_index    int,
    p_index_in_batch int
) RETURNS text


Description:

Generates a localized phone number string.

Algorithm:

Selects a phone pattern from phone_formats for the given locale.
Example patterns:

en_US: '+1 (XXX) XXX-XXXX', '(XXX) XXX-XXXX'

de_DE: '+49 (0XXX) XXXXXXX', '0XXX XXXXXXX'

Selection is deterministic using rand_uniform_01.

Iterates over each character in pattern:

If the character is 'X', generates a digit 0–9 using rand_uniform_01 and appends it.

Otherwise, appends the character unchanged.

Returns the resulting string as the phone number.

Example:

SELECT gen_phone('en_US', 123, 0, 0);
SELECT gen_phone('de_DE', 123, 0, 1);

3.5. gen_email

Name: gen_email

Signature:

gen_email(
    p_locale         text,
    p_seed           int,
    p_batch_index    int,
    p_index_in_batch int
) RETURNS text


Description:

Constructs a realistic e-mail address with several different username patterns to increase variability. The general form is:

<username>@<domain>


Where <domain> comes from email_domains table and <username> is built from first/last names plus an optional numeric suffix.

Steps:

Select domain from email_domains for the given locale:

count rows, generate u_dom ~ U(0,1),

select domain using offset logic.

examples:

en_US: gmail.com, yahoo.com, outlook.com, hotmail.com, example.com, company.com

de_DE: gmail.com, outlook.de, web.de, gmx.de, example.de, firma.de

Select first and last name:

first_raw := pick_random_name(..., 'first')

last_raw := pick_random_name(..., 'last')

Normalize names:

remove all non-alphanumeric characters using regexp_replace(..., '[^a-zA-Z0-9]', '', 'g'),

convert to lowercase,

fallback to user / name if the result is empty.

Generate numeric suffix num:

u_num := rand_uniform_01(...), num := floor(u_num * 100) → an integer from 0 to 99.

Select username pattern:

Using another uniform u_pattern ~ U(0,1), we compute pattern_id = floor(u_pattern * 4) and choose one of:

pattern_id = 0:
username = first || '.' || last
→ john.smith

pattern_id = 1:
username = first || '.' || last || lpad(num::text, 2, '0')
→ john.smith07

pattern_id = 2:
username = substr(first, 1, 1) || '.' || last || lpad(num::text, 2, '0')
→ j.smith42

pattern_id = 3:
username = first || '_' || substr(last, 1, 1) || lpad(num::text, 2, '0')
→ maria_j37

Return final email:

RETURN username || '@' || dom;


All steps are deterministic for given (locale, seed, batch_index, index_in_batch).

Example:

SELECT gen_email('en_US', 123, 0, 0); -- e.g. "john.smith07@gmail.com"
SELECT gen_email('de_DE', 123, 0, 1); -- e.g. "anna.mueller42@web.de"

4. Main generator type and function
4.1. Composite type fake_user

Name: fake_user

Definition:

CREATE TYPE fake_user AS (
    full_name   text,
    address     text,
    latitude    double precision,
    longitude   double precision,
    height_cm   double precision,
    weight_kg   double precision,
    eye_color   text,
    phone       text,
    email       text
);


This type groups all attributes of a generated fake user.

4.2. generate_fake_users

Name: generate_fake_users

Signature:

generate_fake_users(
    p_locale       text,
    p_seed         int,
    p_batch_size   int,
    p_batch_index  int
) RETURNS SETOF fake_user


Parameters:

p_locale – locale code ('en_US', 'de_DE').

p_seed – user-provided seed controlling reproducibility.

p_batch_size – number of users to generate in this batch.

p_batch_index – batch index (page number), used to generate different “pages” of users for the same seed.

Description:

Generates a batch of fake users with all requested attributes.
For each i from 0 to p_batch_size - 1 (index within batch):

Reads physical distribution parameters for the given locale from physical_config:

height_mean_cm, height_std_cm,

weight_mean_kg, weight_std_kg.

Uses the helper functions with (locale, seed, batch_index, index_in_batch = i) to generate:

full_name
via gen_full_name(...) – includes gender-dependent names and titles.

address
via gen_address(...) – localized format, localized lookup data.

latitude, longitude
via rand_on_sphere(...) – uniformly distributed on the sphere.

height_cm
via rand_normal(...) with height parameters.

weight_kg
via rand_normal(...) with weight parameters.

eye_color
via pick_random_eye_color(...).

phone
via gen_phone(...).

email
via gen_email(...).

Returns each record as a row of type fake_user.

All randomness is derived from rand_uniform_01 combined with (p_locale, p_seed, p_batch_index, index_in_batch, stream), therefore all generated data is fully deterministic for:

a given position (batch index + index in batch),

a given (locale, seed).

Example usage:

-- 10 English users, batch 0
SELECT * FROM generate_fake_users('en_US', 123, 10, 0);

-- Same parameters -> exactly the same result
SELECT * FROM generate_fake_users('en_US', 123, 10, 0);

-- Different batch index -> deterministic "next page"
SELECT * FROM generate_fake_users('en_US', 123, 10, 1);

-- Different locale
SELECT * FROM generate_fake_users('de_DE', 123, 10, 0);

5. Benchmark helper (optional)

To measure the performance of the generator, a convenience function is provided.

5.1. benchmark_generate_fake_users

Name: benchmark_generate_fake_users

Signature:

benchmark_generate_fake_users(
    p_locale      text,
    p_seed        int,
    p_batch_size  int,
    p_batch_index int,
    p_iterations  int
) RETURNS TABLE(
    total_users         int,
    total_time_seconds  double precision,
    users_per_second    double precision
)


Description:

Executes the main generator generate_fake_users multiple times and measures total time and throughput (users per second).

Algorithm:

Records start time using clock_timestamp().

For i = 1 .. p_iterations:

calls generate_fake_users(p_locale, p_seed, p_batch_size, p_batch_index + i - 1) using PERFORM.

this generates p_batch_size users per iteration.

Records end time.

Computes:

total_users = p_batch_size * p_iterations,

total_time_seconds = extract(epoch from (end - start)),

users_per_second = total_users / total_time_seconds.

Example:

SELECT *
FROM benchmark_generate_fake_users(
    'en_US',   -- locale
    123,       -- seed
    10000,     -- batch_size
    0,         -- starting batch_index
    10         -- iterations -> 100 000 users total
);


Result can be reported in the project as:

approximately XXX users/second for generating 100 000 fake users
on PostgreSQL <version>, local machine.