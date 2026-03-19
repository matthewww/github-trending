create table repositories (
  id bigserial primary key,
  repo_name text not null,
  description text,
  language text,
  stars_today integer,
  total_stars integer,
  forks integer,
  rank integer,
  collected_at timestamp default now(),
  collected_date date not null default current_date
);

create unique index idx_repo_date_unique on repositories(repo_name, collected_date);
create index idx_repo_date on repositories(repo_name, collected_at);
create index idx_collected_at on repositories(collected_at);
create index idx_language on repositories(language);

create view today_trending as
  select repo_name, language, stars_today, total_stars, forks, rank
  from repositories
  where collected_date = current_date
  order by rank;
